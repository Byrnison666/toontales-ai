from toontales_ai.domain.enums import (
    STAGE_DOWNSTREAM,
    STAGE_IMMEDIATE_NEXT,
    STAGE_PREDECESSORS,
    Stage,
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
