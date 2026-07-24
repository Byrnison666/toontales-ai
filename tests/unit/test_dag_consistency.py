import pytest

from toontales_ai.domain.enums import (
    STAGE_DOWNSTREAM,
    STAGE_IMMEDIATE_NEXT,
    STAGE_PREDECESSORS,
    Stage,
    _build_stage_graph,
)


def _transitive_closure(stage: Stage) -> set[Stage]:
    seen: set[Stage] = set()
    frontier = list(STAGE_IMMEDIATE_NEXT.get(stage, ()))
    while frontier:
        s = frontier.pop()
        if s in seen:
            continue
        seen.add(s)
        frontier.extend(STAGE_IMMEDIATE_NEXT.get(s, ()))
    return seen


def test_stage_downstream_matches_immediate_next_transitive_closure():
    """STAGE_DOWNSTREAM (используется для инвалидации при partial rerun, review.md §3)
    обязан быть полным транзитивным замыканием STAGE_IMMEDIATE_NEXT (используется
    для прогрессии пайплайна) — иначе partial rerun пропустит часть зависимых стадий."""
    for stage in Stage:
        assert set(STAGE_DOWNSTREAM[stage]) == _transitive_closure(stage), stage


def test_every_non_terminal_stage_has_predecessors_defined():
    for stage in Stage:
        for candidate in STAGE_IMMEDIATE_NEXT.get(stage, ()):
            assert candidate in STAGE_PREDECESSORS, f"{candidate} has no predecessors entry"


def test_composition_is_terminal():
    assert STAGE_IMMEDIATE_NEXT[Stage.COMPOSITION] == ()
    assert STAGE_DOWNSTREAM[Stage.COMPOSITION] == ()


@pytest.mark.parametrize("lipsync_enabled", [True, False])
def test_both_dag_modes_are_internally_consistent(lipsync_enabled):
    """Инварианты (downstream = замыкание immediate_next; у каждой не-терминальной
    стадии есть predecessors) обязаны держаться в обоих режимах, не только в дефолтном."""
    downstream, immediate_next, predecessors, _, active = _build_stage_graph(lipsync_enabled=lipsync_enabled)

    # ACTIVE_STAGES — линейный порядок; каждый этап должен идти после всех своих
    # предшественников (иначе процент/отметки прогресса разъедутся с реальностью).
    for stage, preds in predecessors.items():
        for pred in preds:
            assert active.index(pred) < active.index(stage), (lipsync_enabled, stage, pred)

    def closure(stage: Stage) -> set[Stage]:
        seen: set[Stage] = set()
        frontier = list(immediate_next.get(stage, ()))
        while frontier:
            s = frontier.pop()
            if s in seen:
                continue
            seen.add(s)
            frontier.extend(immediate_next.get(s, ()))
        return seen

    for stage in downstream:
        assert set(downstream[stage]) == closure(stage), (lipsync_enabled, stage)
    for stage, nexts in immediate_next.items():
        for candidate in nexts:
            assert candidate in predecessors, (lipsync_enabled, candidate)


def test_voiceover_graph_drops_lipsync_and_joins_video_on_audio():
    _, immediate_next, predecessors, scene_scoped, active = _build_stage_graph(lipsync_enabled=False)
    assert Stage.LIPSYNC not in immediate_next
    assert Stage.LIPSYNC not in scene_scoped
    # VIDEO — join на (IMAGE, AUDIO); COMPOSITION зависит от VIDEO.
    assert set(predecessors[Stage.VIDEO]) == {Stage.IMAGE, Stage.AUDIO}
    assert predecessors[Stage.COMPOSITION] == (Stage.VIDEO,)
    assert immediate_next[Stage.AUDIO] == (Stage.VIDEO,)
    # Показываем пользователю только реальные этапы, без синхронизации губ, и
    # озвучка идёт до video (video берёт длину из озвучки).
    assert Stage.LIPSYNC not in active
    assert active == (Stage.STORYBOARD, Stage.IMAGE, Stage.AUDIO, Stage.VIDEO, Stage.COMPOSITION)
