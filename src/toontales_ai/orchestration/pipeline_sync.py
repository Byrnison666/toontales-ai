"""Celery-сторона оркестрации (sync Session, отдельный sync engine — см. storage/db.py).
Единая точка входа и для poll, и для webhook (review.md §2): оба вызывают
complete_task() под SELECT...FOR UPDATE, что сериализует гонку между ними."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from toontales_ai.adapters.base import ProviderJobResult
from toontales_ai.domain.enums import (
    STAGE_PREDECESSORS,
    CreditTransactionType,
    ProviderJobStatus,
    RunStatus,
    Stage,
    TaskStatus,
)
from toontales_ai.domain.models import CreditTransaction, GenerationRun, PipelineOutbox, Project, Scene, Task, User
from toontales_ai.orchestration.idempotency import (
    credit_charge_key,
    credit_release_key,
    task_idempotency_key,
)
from toontales_ai.orchestration.pipeline_async import MAX_ASSUMED_SCENES
from toontales_ai.orchestration.pipeline_service import plan_next_tasks
from toontales_ai.orchestration.pricing import STAGE_COST

MAX_RETRIES = 3

TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED})


def _stage_task_status(session: Session, run_id: uuid.UUID, stage: Stage, scene_id: uuid.UUID | None) -> TaskStatus | None:
    row = session.execute(
        select(Task.status).where(Task.run_id == run_id, Task.stage == stage, Task.scene_id == scene_id)
    ).scalar_one_or_none()
    return row


def _all_scenes_stage_completed(session: Session, run_id: uuid.UUID, stage: Stage) -> bool:
    scene_count = session.execute(
        select(func.count()).select_from(Scene).where(Scene.generation_run_id == run_id)
    ).scalar_one()
    if scene_count == 0:
        return False
    completed_count = session.execute(
        select(func.count())
        .select_from(Task)
        .where(Task.run_id == run_id, Task.stage == stage, Task.status == TaskStatus.COMPLETED)
    ).scalar_one()
    return completed_count >= scene_count


def _charge(session: Session, task: Task) -> None:
    stmt = (
        pg_insert(CreditTransaction)
        .values(
            user_id=_run_user_id(session, task.run_id),
            run_id=task.run_id,
            task_id=task.id,
            type=CreditTransactionType.CHARGE,
            amount=task.cost,
            idempotency_key=credit_charge_key(task.id),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    session.execute(stmt)


def _release(session: Session, task: Task) -> None:
    stmt = (
        pg_insert(CreditTransaction)
        .values(
            user_id=_run_user_id(session, task.run_id),
            run_id=task.run_id,
            task_id=task.id,
            type=CreditTransactionType.RELEASE,
            amount=task.cost,
            idempotency_key=credit_release_key(task.id),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    session.execute(stmt)
    user = session.execute(select(User).where(User.id == _run_user_id(session, task.run_id)).with_for_update()).scalar_one()
    user.credit_balance += task.cost


def _run_user_id(session: Session, run_id: uuid.UUID) -> uuid.UUID:
    return session.execute(
        select(Project.user_id).join(GenerationRun, GenerationRun.project_id == Project.id).where(GenerationRun.id == run_id)
    ).scalar_one()


def _create_task_and_hold(session: Session, *, run_id: uuid.UUID, stage: Stage, scene_id: uuid.UUID | None, key: str, cost: int) -> uuid.UUID | None:
    """INSERT ... ON CONFLICT DO NOTHING — возвращает id только если строка реально вставлена,
    чтобы hold/outbox не задваивались при гонке двух join-веток (review.md §10)."""
    stmt = (
        pg_insert(Task)
        .values(
            id=uuid.uuid4(),
            run_id=run_id,
            scene_id=scene_id,
            stage=stage,
            provider="",
            status=TaskStatus.PENDING,
            input_snapshot={},
            input_hash=key,
            idempotency_key=key,
            cost=cost,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Task.id)
    )
    return session.execute(stmt).scalar_one_or_none()


def _hold_and_enqueue(session: Session, *, task_id: uuid.UUID, run_id: uuid.UUID, cost: int) -> None:
    user_id = _run_user_id(session, run_id)
    session.execute(
        pg_insert(CreditTransaction)
        .values(
            user_id=user_id,
            run_id=run_id,
            task_id=task_id,
            type=CreditTransactionType.HOLD,
            amount=cost,
            idempotency_key=f"hold:{task_id}",
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    session.execute(
        pg_insert(PipelineOutbox)
        .values(id=uuid.uuid4(), event_type="enqueue_task", aggregate_id=task_id, payload={"task_id": str(task_id)})
        .on_conflict_do_nothing(index_elements=["event_type", "aggregate_id"])
    )


def _advance(session: Session, task: Task) -> None:
    from toontales_ai.domain.enums import STAGE_IMMEDIATE_NEXT

    for candidate in STAGE_IMMEDIATE_NEXT.get(task.stage, ()):
        predecessor_satisfied: dict[Stage, bool] = {}
        if candidate == Stage.COMPOSITION:
            predecessor_satisfied[Stage.LIPSYNC] = _all_scenes_stage_completed(session, task.run_id, Stage.LIPSYNC)
        else:
            for req_stage in STAGE_PREDECESSORS.get(candidate, ()):
                if req_stage == task.stage:
                    predecessor_satisfied[req_stage] = True
                else:
                    predecessor_satisfied[req_stage] = (
                        _stage_task_status(session, task.run_id, req_stage, task.scene_id) == TaskStatus.COMPLETED
                    )

        plans = plan_next_tasks(
            run_id=task.run_id,
            completed_stage=task.stage,
            scene_id=task.scene_id,
            input_version=str(task.id),
            predecessor_satisfied=predecessor_satisfied,
        )
        for plan in plans:
            if plan.stage != candidate:
                continue
            new_id = _create_task_and_hold(
                session, run_id=task.run_id, stage=plan.stage, scene_id=plan.scene_id, key=plan.idempotency_key, cost=plan.cost
            )
            if new_id is not None:
                _hold_and_enqueue(session, task_id=new_id, run_id=task.run_id, cost=plan.cost)


def _materialize_scenes_and_fanout(session: Session, storyboard_task: Task) -> None:
    scenes_data = (storyboard_task.output_snapshot or {}).get("scenes", [])[:MAX_ASSUMED_SCENES]
    for idx, scene_data in enumerate(scenes_data):
        scene = Scene(
            generation_run_id=storyboard_task.run_id,
            scene_index=idx,
            script_text=scene_data.get("script_text", ""),
            image_prompt=scene_data.get("image_prompt", ""),
            camera_movement=scene_data.get("camera_movement", ""),
            mood_notes=scene_data.get("mood_notes", ""),
            scene_metadata=scene_data,
        )
        session.add(scene)
        session.flush()

        for stage in (Stage.IMAGE, Stage.AUDIO):
            key = task_idempotency_key(
                run_id=storyboard_task.run_id, stage=stage, scene_id=scene.id, input_version=str(scene.id)
            )
            new_id = _create_task_and_hold(
                session, run_id=storyboard_task.run_id, stage=stage, scene_id=scene.id, key=key, cost=STAGE_COST[stage]
            )
            if new_id is not None:
                _hold_and_enqueue(session, task_id=new_id, run_id=storyboard_task.run_id, cost=STAGE_COST[stage])


def complete_task(session: Session, *, task_id: uuid.UUID, result: ProviderJobResult) -> None:
    task = session.execute(select(Task).where(Task.id == task_id).with_for_update()).scalar_one()

    if task.status in TERMINAL_STATUSES:
        return  # already resolved — второй из poll/webhook гонки становится no-op

    if result.status == ProviderJobStatus.SUCCEEDED:
        task.status = TaskStatus.COMPLETED
        task.output_snapshot = {"artifacts": list(result.artifacts)}
        task.finished_at = datetime.now(timezone.utc)
        task.provider_job_id = result.provider_job_id
        task.provider_status = result.status
        _charge(session, task)

        if task.stage == Stage.STORYBOARD:
            _materialize_scenes_and_fanout(session, task)
        else:
            _advance(session, task)

    elif result.status == ProviderJobStatus.FAILED:
        if task.retry_count >= MAX_RETRIES:
            task.status = TaskStatus.FAILED
            task.error_payload = {"code": result.error_code, "detail": result.error_detail}
            task.finished_at = datetime.now(timezone.utc)
            _release(session, task)
        else:
            task.retry_count += 1
            task.status = TaskStatus.RETRY_SCHEDULED
            task.error_payload = {"code": result.error_code, "detail": result.error_detail}

    project_id = session.execute(
        select(Project.id).join(GenerationRun, GenerationRun.project_id == Project.id).where(GenerationRun.id == task.run_id)
    ).scalar_one()
    stage_status, task_status_value, error_payload = task.stage, task.status, task.error_payload
    session.commit()

    _publish_task_event(
        run_id=task.run_id,
        project_id=project_id,
        task_id=task.id,
        stage=stage_status,
        status=task_status_value,
        error_payload=error_payload,
    )


def _publish_task_event(*, run_id, project_id, task_id, stage: Stage, status: TaskStatus, error_payload: dict | None) -> None:
    from toontales_ai.domain.enums import Stage as _Stage
    from toontales_ai.ws.events import publish_event

    stage_order = list(_Stage)
    stage_index = stage_order.index(stage)
    progress = int(round((stage_index + 1) / len(stage_order) * 100)) if status == TaskStatus.COMPLETED else int(
        round(stage_index / len(stage_order) * 100)
    )
    publish_event(
        run_id=run_id,
        project_id=project_id,
        task_id=task_id,
        stage=stage.value,
        stage_index=stage_index,
        total_stages=len(stage_order),
        status=status.value,
        progress=progress,
        message=f"{stage.value}: {status.value}",
        error={"code": error_payload.get("code"), "detail": error_payload.get("detail")} if error_payload else None,
    )
