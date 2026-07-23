"""Прайсинг: цена ролика детерминирована из выбранной длительности.

Модель (v3, посекундная — без резерва):
* Пользователь выбирает длительность D секунд. Цена = price_from_duration(D),
  известна ДО старта и показывается клиенту.
* На старте баланс НЕ трогается (ни резерва, ни списания) — только проверка,
  что средств хватает (start_run, с учётом активных запусков).
* Работа идёт до конца без обрыва. Списание одно, на успешной COMPOSITION,
  ровно price_from_duration(D) — независимо от фактической себестоимости. Если
  сцене нужно чуть больше секунд, чтобы закончиться — перерасход наш.
* Провал → не списываем ничего.

Искра — единица СЕБЕСТОИМОСТИ (1 искра = settings.spark_cost_usd). Списание идёт
по себестоимости, БЕЗ наценки: наценка ×price_markup берётся один раз в цене
пакета искр (package_price_rub). Умножать наценку и при списании нельзя — markov².

Себестоимость/сек берётся из тех же тарифов, что real_cost.py — держать синхронно.
"""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from toontales_ai.orchestration import real_cost

PRICING_VERSION = "v3"

# Границы выбираемой длительности (сек). 5с — один короткий клип, 90с — ~15 сцен;
# выше растёт риск сбоя на многосценных роликах и время генерации.
MIN_DURATION_SECONDS = 5
MAX_DURATION_SECONDS = 90

# Целевая длина одного клипа-сцены. Runway режет клип в диапазоне 2..10с
# (adapters/video/runway.py MIN/MAX_DURATION_SECONDS — держать синхронно),
# поэтому число сцен = D / TARGET, но длина клипа клампится в этот диапазон.
TARGET_CLIP_SECONDS = 6
_CLIP_MIN = 2
_CLIP_MAX = 10

# Средняя плотность озвучки. ~150 слов/мин × ~5 символов = ~12.5 симв/с; берём 15
# с запасом. Аудио — не главный драйвер (в voiceover ~$0.0015/с против $0.05/с
# видео), поэтому точность второстепенна.
AUDIO_CHARS_PER_SECOND = Decimal("15")

# Фиксированная себестоимость раскадровки на ролик (Anthropic Haiku, верхняя
# граница: max_tokens=4096 выхода + ~4000 входа). Амортизируется на всю длину.
STORYBOARD_USD = Decimal("0.025")


def scene_count_for_duration(seconds: int) -> int:
    """Сколько сцен нарезать под длительность. Длина клипа держится около
    TARGET_CLIP_SECONDS, но не выходит за [2, 10] Runway."""
    n = max(1, int((Decimal(seconds) / TARGET_CLIP_SECONDS).to_integral_value(rounding=ROUND_HALF_UP)))
    # Клип не длиннее 10с -> при длинном ролике сцен должно быть достаточно.
    import math

    n = max(n, math.ceil(seconds / _CLIP_MAX))
    # Клип не короче 2с -> не плодим больше сцен, чем влезает по нижней границе.
    n = min(n, max(1, seconds // _CLIP_MIN))
    return n


def clip_seconds_for(seconds: int, scene_count: int) -> int:
    """Длина клипа одной сцены (целые секунды, в диапазоне Runway)."""
    raw = int((Decimal(seconds) / scene_count).to_integral_value(rounding=ROUND_HALF_UP))
    return max(_CLIP_MIN, min(_CLIP_MAX, raw))


def _cost_usd_for_duration(seconds: int) -> Decimal:
    """Себестоимость ролика длительности seconds в USD. Детерминирована — те же
    тарифы, что real_cost.py, взятые по выбранной длине, а не по факту."""
    from toontales_ai.config.settings import get_settings

    per_second_video = real_cost.RUNWAY_VIDEO_CREDITS_PER_SECOND * real_cost.RUNWAY_USD_PER_CREDIT
    per_second_audio = AUDIO_CHARS_PER_SECOND * real_cost.ELEVENLABS_USD_PER_CHARACTER
    per_second = per_second_video + per_second_audio
    if get_settings().lipsync_enabled:
        per_second += real_cost.SYNC_LIPSYNC_USD_PER_SECOND

    scenes = scene_count_for_duration(seconds)
    image = scenes * real_cost.RUNWAY_IMAGE_CREDITS_PER_IMAGE * real_cost.RUNWAY_USD_PER_CREDIT

    return Decimal(seconds) * per_second + image + STORYBOARD_USD


def price_from_duration(seconds: int) -> int:
    """Цена ролика в искрах по выбранной длительности. Детерминирована, известна
    до старта, списывается один раз на успехе. Округление вверх."""
    from toontales_ai.config.settings import get_settings

    raw = _cost_usd_for_duration(seconds) / get_settings().spark_cost_usd
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


def clamp_duration(seconds: int) -> int:
    """Зажать длительность в допустимый диапазон. Валидация входа — на границе API
    (schemas), здесь defensive."""
    return max(MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, seconds))


# ---------- админ-сверка маржи ----------


def revenue_usd(sparks: int) -> Decimal:
    """Сколько сервис выручил за эти искры при продаже (расчётно, по цене пакета).
    Завышает для искр, начисленных вручную (billing.topup) — их никто не оплачивал."""
    from toontales_ai.config.settings import get_settings

    settings = get_settings()
    return Decimal(sparks) * settings.spark_cost_usd * settings.price_markup


def actual_markup(sparks: int, cost_usd: Decimal | None) -> Decimal | None:
    """Фактическая наценка: выручка / себестоимость. None при неизвестной/нулевой
    себестоимости."""
    if cost_usd is None or cost_usd <= 0:
        return None
    return (revenue_usd(sparks) / cost_usd).quantize(Decimal("0.01"))


# ---------- продажа искр ----------

# Размеры пакетов в искрах. Ориентир — типовые ролики: ~10с, ~30с, ~90с роликов
# соответственно. Цена не хранится — считается из себестоимости (package_price_rub),
# чтобы наценка не разъехалась с тарифами.
SPARK_PACKAGE_SIZES: tuple[int, ...] = (3_500, 10_000, 35_000)

# До скольки рублей округлять витринную цену. Всегда ВВЕРХ.
PRICE_ROUNDING_RUB = Decimal("10")


def package_price_rub(sparks: int) -> Decimal:
    """Розничная цена пакета в рублях: себестоимость искр × наценка × курс с
    буфером, округлённая вверх."""
    from toontales_ai.config.settings import get_settings

    settings = get_settings()
    floor_rub = (
        Decimal(sparks)
        * settings.spark_cost_usd
        * settings.price_markup
        * settings.usd_rub_rate
        * (Decimal("1") + settings.usd_rub_buffer)
    )
    return (floor_rub / PRICE_ROUNDING_RUB).to_integral_value(rounding=ROUND_CEILING) * PRICE_ROUNDING_RUB
