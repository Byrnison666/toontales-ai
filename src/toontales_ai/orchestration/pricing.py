from toontales_ai.domain.enums import Stage

# Стоимость стадии в минимальных единицах кредита (integer). Плейсхолдер для MVP —
# реальная версия прайсинга должна быть версионирована (review.md §10, пробел
# "предварительная смета"); здесь фиксированная версия v1 без per-provider вариации.
PRICING_VERSION = "v1"

STAGE_COST: dict[Stage, int] = {
    Stage.STORYBOARD: 50,
    Stage.IMAGE: 30,
    Stage.VIDEO: 200,
    Stage.AUDIO: 20,
    Stage.LIPSYNC: 20,  # real Sync.so API call — то же порядок цены, что AUDIO (ElevenLabs)
    Stage.COMPOSITION: 10,
}


def estimate_run_cost(scene_count: int) -> int:
    """Грубая смета до старта run: storyboard один раз + per-scene стадии.
    Используется как GenerationRun.max_budget / estimated_cost (review.md §10).
    В voiceover-режиме (settings.lipsync_enabled=False) стадии LIPSYNC нет."""
    from toontales_ai.config.settings import get_settings

    per_scene = STAGE_COST[Stage.IMAGE] + STAGE_COST[Stage.VIDEO] + STAGE_COST[Stage.AUDIO]
    if get_settings().lipsync_enabled:
        per_scene += STAGE_COST[Stage.LIPSYNC]
    return STAGE_COST[Stage.STORYBOARD] + scene_count * per_scene + STAGE_COST[Stage.COMPOSITION]
