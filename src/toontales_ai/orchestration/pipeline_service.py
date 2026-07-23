"""Pure бизнес-логика DAG/idempotency — без сессии БД и без Celery.
Используется и async (FastAPI), и sync (Celery) стороной orchestration
(см. pipeline_async.py / pipeline_sync.py)."""

import uuid
from dataclasses import dataclass

from toontales_ai.domain.enums import STAGE_IMMEDIATE_NEXT, STAGE_PREDECESSORS, Stage
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.pricing import stage_hold


@dataclass(frozen=True, slots=True)
class TaskPlan:
    stage: Stage
    scene_id: uuid.UUID | None
    idempotency_key: str
    cost: int


def plan_next_tasks(
    *,
    run_id: uuid.UUID,
    completed_stage: Stage,
    scene_id: uuid.UUID | None,
    input_version: str,
    predecessor_satisfied: dict[Stage, bool],
) -> list[TaskPlan]:
    """Для каждой возможной следующей стадии проверяет, что ВСЕ её предшественники
    удовлетворены (predecessor_satisfied передаётся вызывающей стороной, которая
    уже сходила в БД за статусами соседей). Composition — run-level join, вызывающая
    сторона передаёт scene_id=None и агрегированный флаг по всем сценам run."""
    plans: list[TaskPlan] = []
    for candidate in STAGE_IMMEDIATE_NEXT.get(completed_stage, ()):
        required = STAGE_PREDECESSORS.get(candidate, ())
        if not all(predecessor_satisfied.get(stage, False) for stage in required):
            continue
        candidate_scene_id = None if candidate == Stage.COMPOSITION else scene_id
        key = task_idempotency_key(
            run_id=run_id,
            stage=candidate,
            scene_id=candidate_scene_id,
            input_version=input_version,
        )
        plans.append(
            TaskPlan(
                stage=candidate,
                scene_id=candidate_scene_id,
                idempotency_key=key,
                cost=stage_hold(candidate),
            )
        )
    return plans
