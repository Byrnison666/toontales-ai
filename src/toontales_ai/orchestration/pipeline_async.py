"""FastAPI-сторона оркестрации: старт run и partial rerun.
Единая Postgres-транзакция фиксирует GenerationRun/Task/CreditTransaction/Outbox;
сама постановка в Celery происходит отдельным dispatcher-ом ПОСЛЕ commit
(см. orchestration/outbox_dispatcher.py)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.domain.enums import (
    CreditTransactionType,
    RunStatus,
    RunTrigger,
    Stage,
)
from toontales_ai.domain.models import CreditTransaction, GenerationRun, PipelineOutbox, Task, User
from toontales_ai.orchestration.idempotency import credit_hold_key, task_idempotency_key
from toontales_ai.orchestration.pricing import STAGE_COST, estimate_run_cost

MAX_ASSUMED_SCENES = 6  # ориентир из v2.md: "до 5-6 сцен на 30-секундный ролик"


class InsufficientCreditsError(Exception):
    pass


async def start_run(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    script_text: str,
) -> GenerationRun:
    max_budget = estimate_run_cost(MAX_ASSUMED_SCENES)
    storyboard_cost = STAGE_COST[Stage.STORYBOARD]

    # SELECT ... FOR UPDATE на баланс пользователя перед hold (review.md §4).
    user = (
        await session.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one()
    if user.credit_balance < storyboard_cost:
        raise InsufficientCreditsError(f"balance {user.credit_balance} < required {storyboard_cost}")

    run = GenerationRun(
        project_id=project_id,
        trigger=RunTrigger.INITIAL,
        status=RunStatus.RUNNING,
        estimated_cost=max_budget,
        max_budget=max_budget,
    )
    session.add(run)
    await session.flush()

    key = task_idempotency_key(
        run_id=run.id, stage=Stage.STORYBOARD, scene_id=None, input_version=script_text
    )
    task = Task(
        run_id=run.id,
        scene_id=None,
        stage=Stage.STORYBOARD,
        provider="llm",
        input_snapshot={"script_text": script_text},
        input_hash=key,
        idempotency_key=key,
        cost=storyboard_cost,
    )
    session.add(task)
    await session.flush()

    user.credit_balance -= storyboard_cost
    session.add(
        CreditTransaction(
            user_id=user_id,
            run_id=run.id,
            task_id=task.id,
            type=CreditTransactionType.HOLD,
            amount=storyboard_cost,
            idempotency_key=credit_hold_key(task.id),
        )
    )
    session.add(PipelineOutbox(event_type="enqueue_task", aggregate_id=task.id, payload={"task_id": str(task.id)}))

    await session.commit()
    return run


async def request_partial_rerun(
    session: AsyncSession,
    *,
    parent_run_id: uuid.UUID,
    stage: Stage,
    scene_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> GenerationRun:
    """Новый GenerationRun с parent_run_id; старые Task/Scene не изменяются
    (review.md §3). Пересчитывается выбранный stage + всё, что от него зависит,
    через STAGE_DOWNSTREAM (полное транзитивное замыкание, в отличие от
    STAGE_IMMEDIATE_NEXT, используемого при обычной прогрессии)."""
    from toontales_ai.domain.enums import STAGE_DOWNSTREAM

    parent_run = (
        await session.execute(select(GenerationRun).where(GenerationRun.id == parent_run_id))
    ).scalar_one()

    # estimated_cost/max_budget — информативная смета на весь downstream-каскад;
    # реально резервируется (hold) только стоимость первой стадии, остальное
    # холдируется инкрементально в pipeline_sync._advance по мере прогрессии
    # (иначе downstream-стадии задвоили бы hold: один здесь, второй в _advance).
    stages_to_rerun = (stage, *STAGE_DOWNSTREAM.get(stage, ()))
    estimated_total_cost = sum(STAGE_COST[s] for s in stages_to_rerun)
    initial_hold_cost = STAGE_COST[stage]

    user = (
        await session.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one()
    if user.credit_balance < estimated_total_cost:
        raise InsufficientCreditsError(f"balance {user.credit_balance} < required {estimated_total_cost}")

    new_run = GenerationRun(
        project_id=parent_run.project_id,
        trigger=RunTrigger.PARTIAL_RERUN,
        parent_run_id=parent_run.id,
        status=RunStatus.RUNNING,
        estimated_cost=estimated_total_cost,
        max_budget=estimated_total_cost,
        character_version_id=parent_run.character_version_id,
    )
    session.add(new_run)
    await session.flush()

    # Только сам запрошенный stage ставится в очередь сразу; его downstream-стадии
    # будут созданы прогрессией через pipeline_sync._advance по мере завершения (join-логика).
    key = task_idempotency_key(
        run_id=new_run.id, stage=stage, scene_id=scene_id, input_version=str(uuid.uuid4())
    )
    task = Task(
        run_id=new_run.id,
        scene_id=scene_id,
        stage=stage,
        provider="",
        input_snapshot={},
        input_hash=key,
        idempotency_key=key,
        cost=STAGE_COST[stage],
    )
    session.add(task)
    await session.flush()

    user.credit_balance -= initial_hold_cost
    session.add(
        CreditTransaction(
            user_id=user_id,
            run_id=new_run.id,
            task_id=task.id,
            type=CreditTransactionType.HOLD,
            amount=initial_hold_cost,
            idempotency_key=credit_hold_key(task.id),
        )
    )
    session.add(PipelineOutbox(event_type="enqueue_task", aggregate_id=task.id, payload={"task_id": str(task.id)}))

    await session.commit()
    return new_run
