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
from toontales_ai.adapters.moderation import get_moderation_adapter, moderate_text_or_raise
from toontales_ai.domain.models import CreditTransaction, GenerationRun, PipelineOutbox, Scene, Task, User
from toontales_ai.orchestration.idempotency import credit_hold_key, task_idempotency_key
from toontales_ai.orchestration.pricing import STAGE_COST, estimate_run_cost

MAX_ASSUMED_SCENES = 6  # ориентир из v2.md: "до 5-6 сцен на 30-секундный ролик"


class InsufficientCreditsError(Exception):
    pass


class InvalidPartialRerunError(Exception):
    """scene_id не принадлежит parent_run, либо не соответствует scope стадии
    (review.md: IDOR — раньше проверялся только ownership run, но не то, что
    scene_id действительно относится к этому run/пользователю)."""

    pass


async def start_run(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    script_text: str,
) -> GenerationRun:
    # Модерация пользовательского текста до создания run/hold (v2.md §3: "готовность
    # к добавлению модерации... промпты сохраняются для аудита уже в MVP").
    await moderate_text_or_raise(get_moderation_adapter(), script_text)

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
    STAGE_IMMEDIATE_NEXT, используемого при обычной прогрессии).

    Известное ограничение (не в объёме этого фикса): для join-стадий (LIPSYNC
    требует и VIDEO, и AUDIO; COMPOSITION требует LIPSYNC по всем сценам)
    предшественники, НЕ входящие в перезапускаемую цепочку STAGE_DOWNSTREAM,
    существуют только в parent_run и не копируются в new_run. Например, partial
    rerun стадии VIDEO не сможет продвинуться до LIPSYNC, пока AUDIO-задача той
    же сцены не будет также представлена в new_run. Полное решение — копирование
    завершённых sibling-Task (и их MediaAsset) из parent_run в new_run — отдельная
    архитектурная задача."""
    from toontales_ai.domain.enums import SCENE_SCOPED_STAGES, STAGE_DOWNSTREAM

    parent_run = (
        await session.execute(select(GenerationRun).where(GenerationRun.id == parent_run_id))
    ).scalar_one()

    # IDOR-проверка (review.md §6): scene_id обязателен для scene-scoped стадий и должен
    # принадлежать именно parent_run, иначе чужая сцена может быть прочитана/переотправлена
    # провайдеру под видом ownership-проверенного run.
    if stage in SCENE_SCOPED_STAGES:
        if scene_id is None:
            raise InvalidPartialRerunError(f"scene_id is required for scene-scoped stage {stage.value}")
        scene_owned = (
            await session.execute(
                select(Scene.id).where(Scene.id == scene_id, Scene.generation_run_id == parent_run_id)
            )
        ).scalar_one_or_none()
        if scene_owned is None:
            raise InvalidPartialRerunError("scene_id does not belong to parent_run")
    elif scene_id is not None:
        raise InvalidPartialRerunError(f"scene_id must be omitted for run-scoped stage {stage.value}")

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

    # Scene привязана к GenerationRun (review.md §3), поэтому new_run без своих Scene
    # не может пройти join-проверки на предшествующие стадии/composition (P0: раньше
    # partial rerun падал с "no scenes to compose", т.к. _all_scenes_stage_completed
    # и _run_composition ищут Scene по generation_run_id == новый run). Копируем Scene
    # из parent_run с новыми id и ремапим запрошенный scene_id на копию.
    parent_scenes = (
        await session.execute(
            select(Scene).where(Scene.generation_run_id == parent_run_id).order_by(Scene.scene_index)
        )
    ).scalars().all()
    scene_id_map: dict[uuid.UUID, uuid.UUID] = {}
    for parent_scene in parent_scenes:
        new_scene = Scene(
            generation_run_id=new_run.id,
            scene_index=parent_scene.scene_index,
            script_text=parent_scene.script_text,
            image_prompt=parent_scene.image_prompt,
            camera_movement=parent_scene.camera_movement,
            mood_notes=parent_scene.mood_notes,
            scene_metadata=parent_scene.scene_metadata,
        )
        session.add(new_scene)
        await session.flush()
        scene_id_map[parent_scene.id] = new_scene.id

    new_scene_id = scene_id_map[scene_id] if scene_id is not None else None

    # Только сам запрошенный stage ставится в очередь сразу; его downstream-стадии
    # будут созданы прогрессией через pipeline_sync._advance по мере завершения (join-логика).
    key = task_idempotency_key(
        run_id=new_run.id, stage=stage, scene_id=new_scene_id, input_version=str(uuid.uuid4())
    )
    task = Task(
        run_id=new_run.id,
        scene_id=new_scene_id,
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
