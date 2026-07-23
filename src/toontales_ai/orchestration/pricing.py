"""Прайсинг: себестоимость в USD, баланс и списания в искрах, наценка в пакетах.

Искра — единица СЕБЕСТОИМОСТИ: 1 искра = settings.spark_cost_usd затрат
провайдерам. Списание идёт один в один по затратам, БЕЗ наценки. Наценка берётся
ровно один раз — в цене пакета искр (SPARK_PACKAGES): пакет продаётся за
price_markup × свою себестоимость. Отсюда инвариант: сколько бы искр клиент ни
потратил, он заплатил за них втрое больше, чем они стоили нам.

Наценка при списании И при продаже дала бы markup² — поэтому price_sparks
намеренно не умножает ни на что.

Клиент никогда не видит себестоимость в деньгах — только искры (клиентские схемы
в api/v1/schemas.py); USD остаётся в админской выдаче (api/v1/admin.py).

Две величины, которые легко перепутать:

* ХОЛД (stage_hold) — верхняя граница стоимости стадии, блокируется на балансе ДО
  запуска. Считается из STAGE_COST_USD_MAX — худшего случая по каждому провайдеру.
* СПИСАНИЕ (price_sparks) — по факту, из Task.real_cost_usd после завершения
  стадии. Разница возвращается на баланс (pipeline_sync._settle).

Такая схема держит наценку при любой длине сцены: смета с фиксированными
допущениями (5 с видео) давала бы ×1.5 на десятисекундной сцене.
"""

from decimal import ROUND_CEILING, Decimal

from toontales_ai.domain.enums import Stage

PRICING_VERSION = "v2"

# Верхняя граница себестоимости стадии в USD. Держать синхронно с тарифами в
# orchestration/real_cost.py — это те же формулы, взятые в максимуме допустимых
# провайдером параметров. Занижение здесь не приводит к убытку (списание идёт по
# факту), но урезает списание клампом в _settle: цена не может превысить холд,
# поэтому слишком низкий холд = потерянная наценка.
STAGE_COST_USD_MAX: dict[Stage, Decimal] = {
    # max_tokens=4096 на выходе + ~4000 токенов входа (схема + сюжет), Haiku 4.5.
    Stage.STORYBOARD: Decimal("0.025"),
    # gen4_image: 5 кредитов Runway на изображение, фикс.
    Stage.IMAGE: Decimal("0.05"),
    # gen4_turbo, MAX_DURATION_SECONDS=10 (adapters/video/runway.py).
    Stage.VIDEO: Decimal("0.50"),
    # ElevenLabs $0.0001/символ. Верхняя граница — весь лимит ввода (4000
    # символов, schemas.GenerateProjectRequest) в одной сцене: раскадровка не
    # гарантирует распределения текста по сценам, а maxLength в scene-схеме
    # grammar-constrained decoding не поддерживает (adapters/storyboard/anthropic.py).
    # Держать 4000 синхронно с лимитом script_text.
    Stage.AUDIO: Decimal("0.40"),
    # Sync.so lipsync-2, те же 10 секунд, что у VIDEO.
    Stage.LIPSYNC: Decimal("0.45"),
    # ffmpeg на своих мощностях: real_cost.py возвращает 0, поэтому и цена 0.
    Stage.COMPOSITION: Decimal("0"),
}


def price_sparks(cost_usd: Decimal) -> int:
    """Сколько искр списать за работу себестоимостью cost_usd. Один в один, без
    наценки — она уже собрана при продаже пакета.
    Округление вверх и на стадию, а не на run: списания идут по задачам, ledger
    целочисленный — дробить искру негде. Чем мельче номинал искры, тем меньше
    округление задирает фактическую наценку выше price_markup."""
    from toontales_ai.config.settings import get_settings

    raw = cost_usd / get_settings().spark_cost_usd
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


def revenue_usd(sparks: int) -> Decimal:
    """Сколько сервис выручил за эти искры при продаже. Расчётная величина: она
    верна для искр, купленных пакетами, и завышает выручку для начисленных
    вручную (billing.topup) — их никто не оплачивал."""
    from toontales_ai.config.settings import get_settings

    settings = get_settings()
    return Decimal(sparks) * settings.spark_cost_usd * settings.price_markup


def actual_markup(sparks: int, cost_usd: Decimal | None) -> Decimal | None:
    """Фактическая наценка: выручка / себестоимость. None, если себестоимость
    неизвестна или нулевая — «наценка ∞» на бесплатной composition бессмысленна."""
    if cost_usd is None or cost_usd <= 0:
        return None
    return (revenue_usd(sparks) / cost_usd).quantize(Decimal("0.01"))


def stage_hold(stage: Stage) -> int:
    """Сколько искр блокировать на балансе до запуска стадии."""
    return price_sparks(STAGE_COST_USD_MAX[stage])


# ---------- продажа искр ----------

# Размеры пакетов в искрах. Привязаны к типовому ролику (~3300 искр): «на один»,
# «на три», «на десять». Цена не хранится — считается из себестоимости, чтобы
# наценка не разъехалась с прайсом провайдеров при правке тарифов.
SPARK_PACKAGE_SIZES: tuple[int, ...] = (3_500, 10_000, 35_000)

# До скольки рублей округлять витринную цену. Округление всегда ВВЕРХ: вниз —
# значит продать дешевле себестоимости×markup.
PRICE_ROUNDING_RUB = Decimal("10")


def package_price_rub(sparks: int) -> Decimal:
    """Розничная цена пакета в рублях: себестоимость искр × наценка × курс с
    буфером, округлённая вверх. Буфер закрывает движение курса между правками
    settings.usd_rub_rate — без него маржа падает вместе с рублём."""
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


def estimate_run_cost(scene_count: int) -> int:
    """Полный холд на run: storyboard один раз + per-scene стадии.
    Используется как GenerationRun.max_budget / estimated_cost (review.md §10).
    В voiceover-режиме (settings.lipsync_enabled=False) стадии LIPSYNC нет."""
    from toontales_ai.config.settings import get_settings

    per_scene = stage_hold(Stage.IMAGE) + stage_hold(Stage.VIDEO) + stage_hold(Stage.AUDIO)
    if get_settings().lipsync_enabled:
        per_scene += stage_hold(Stage.LIPSYNC)
    return stage_hold(Stage.STORYBOARD) + scene_count * per_scene + stage_hold(Stage.COMPOSITION)
