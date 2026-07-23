from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from toontales_ai.domain.enums import Stage

# ВАЖНО про смысл этого модуля: он не измеряет расход, а СЧИТАЕТ его по тарифам
# ниже. Если провайдер поднимет цену, ни одна цифра здесь не изменится — расчёт
# останется прежним, а реальные счета вырастут. Дрейф тарифов невидим изнутри
# по построению; единственный источник правды — инвойсы провайдеров.
# Отсюда три способа его поймать:
#   1. TARIFF_CHECKED_AT + метрика возраста — напоминание сверить руками;
#   2. счётчик клампа в pipeline_sync._settle — реальность вышла за верхнюю
#      границу, значит тариф уже уехал;
#   3. admin/provider-spend — расчётный расход по провайдерам, который сверяется
#      с суммой в инвойсе.

# Дата последней ручной сверки тарифа с прайс-листом провайдера. Обновлять
# ВМЕСТЕ с цифрами: устаревшая дата поднимает toontales_tariff_age_days и алерт.
TARIFF_CHECKED_AT: dict[str, date] = {
    "anthropic": date(2026, 7, 21),
    "runway": date(2026, 7, 23),
    "elevenlabs": date(2026, 7, 21),
    "sync": date(2026, 7, 21),
}

# Какой провайдер обслуживает стадию — для сверки расчёта с инвойсом.
# composition считается на своих мощностях, внешнего счёта у неё нет.
STAGE_PROVIDER: dict[Stage, str] = {
    Stage.STORYBOARD: "anthropic",
    Stage.IMAGE: "runway",
    Stage.VIDEO: "runway",
    Stage.AUDIO: "elevenlabs",
    Stage.LIPSYNC: "sync",
    Stage.COMPOSITION: "self",
}

# Все тарифы дрейфуют и требуют периодической ревизии.
# Источник: Anthropic pricing, Claude Haiku 4.5; WebSearch, сверено 2026-07-21.
ANTHROPIC_INPUT_USD_PER_TOKEN = Decimal("1.00") / Decimal("1000000")
ANTHROPIC_OUTPUT_USD_PER_TOKEN = Decimal("5.00") / Decimal("1000000")

# Источник: Runway API pricing, gen4_image и gen4_turbo; docs.dev.runwayml.com,
# сверено 2026-07-23. Video-тариф модельно-зависимый: gen4_turbo = 5 кред/с,
# gen4.5 = 10 кред/с. Держать синхронно с settings.runway_video_model.
RUNWAY_USD_PER_CREDIT = Decimal("0.01")
RUNWAY_IMAGE_CREDITS_PER_IMAGE = Decimal("5")
RUNWAY_VIDEO_CREDITS_PER_SECOND = Decimal("5")

# Источник: ElevenLabs pricing, eleven_multilingual_v2; WebSearch, сверено 2026-07-21.
ELEVENLABS_USD_PER_CHARACTER = Decimal("0.10") / Decimal("1000")

# Источник: Sync.so pricing, lipsync-2; WebSearch, сверено 2026-07-21.
SYNC_LIPSYNC_USD_PER_SECOND = Decimal("0.045")

USD_QUANTUM = Decimal("0.000001")


def _usage_value(usage: dict[str, Any], field: str) -> Decimal | None:
    value = usage.get(field)
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not decimal_value.is_finite() or decimal_value < 0:
        return None
    return decimal_value


def compute_real_cost_usd(stage: Stage, usage: dict[str, Any] | None) -> Decimal | None:
    if stage == Stage.COMPOSITION:
        return Decimal("0").quantize(USD_QUANTUM)
    if usage is None:
        return None

    if stage == Stage.STORYBOARD:
        input_tokens = _usage_value(usage, "input_tokens")
        output_tokens = _usage_value(usage, "output_tokens")
        if input_tokens is None or output_tokens is None:
            return None
        cost = (
            input_tokens * ANTHROPIC_INPUT_USD_PER_TOKEN
            + output_tokens * ANTHROPIC_OUTPUT_USD_PER_TOKEN
        )
    elif stage == Stage.IMAGE:
        images = _usage_value(usage, "images")
        if images is None:
            return None
        cost = images * RUNWAY_IMAGE_CREDITS_PER_IMAGE * RUNWAY_USD_PER_CREDIT
    elif stage == Stage.VIDEO:
        duration_seconds = _usage_value(usage, "duration_seconds")
        if duration_seconds is None:
            return None
        cost = duration_seconds * RUNWAY_VIDEO_CREDITS_PER_SECOND * RUNWAY_USD_PER_CREDIT
    elif stage == Stage.AUDIO:
        characters = _usage_value(usage, "characters")
        if characters is None:
            return None
        cost = characters * ELEVENLABS_USD_PER_CHARACTER
    elif stage == Stage.LIPSYNC:
        duration_seconds = _usage_value(usage, "duration_seconds")
        if duration_seconds is None:
            return None
        cost = duration_seconds * SYNC_LIPSYNC_USD_PER_SECOND
    else:
        return None

    try:
        return cost.quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
