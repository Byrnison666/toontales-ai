"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.

Регрессия для _copy_completed_context (pipeline_async.py): partial rerun
scene-scoped стадии (VIDEO) с downstream join-стадиями (LIPSYNC требует
VIDEO+AUDIO; COMPOSITION требует LIPSYNC по всем сценам) должен видеть
завершённые sibling-Task/MediaAsset внутри нового run, а не только в parent_run."""

import uuid

from toontales_ai.adapters.base import ProviderJobResult
from toontales_ai.domain.enums import MediaKind, ProviderJobStatus, RetentionClass, RunStatus, Stage, TaskStatus
from toontales_ai.orchestration.pipeline_sync import complete_task
from toontales_ai.domain.models import CreditTransaction, GenerationRun, MediaAsset, Project, Scene, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.pipeline_async import request_partial_rerun
from toontales_ai.storage.db import AsyncSessionLocal

_MEDIA_KIND_BY_STAGE = {Stage.IMAGE: MediaKind.IMAGE, Stage.VIDEO: MediaKind.VIDEO, Stage.AUDIO: MediaKind.AUDIO}


def _seed_completed_pipeline_up_to_lipsync(session, *, scene_count: int = 2):
    """Сцены со всеми предшествующими LIPSYNC стадиями завершёнными: STORYBOARD,
    IMAGE, VIDEO, AUDIO по каждой сцене + их MediaAsset."""
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=10_000)
    session.add(user)
    session.flush()

    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()

    run = GenerationRun(project_id=project.id, status=RunStatus.COMPLETED, duration_seconds=30, price=3170)
    session.add(run)
    session.flush()

    # rerun разрешён только с полностью оплаченного родителя — досеиваем CHARGE на
    # полную цену (как сделал бы _charge_run по успеху COMPOSITION).
    from toontales_ai.domain.enums import CreditTransactionType
    from toontales_ai.orchestration.idempotency import credit_run_charge_key

    session.add(
        CreditTransaction(
            user_id=user.id, run_id=run.id, type=CreditTransactionType.CHARGE,
            amount=run.price, idempotency_key=credit_run_charge_key(run.id),
        )
    )
    session.flush()

    storyboard_key = task_idempotency_key(run_id=run.id, stage=Stage.STORYBOARD, scene_id=None, input_version="v1")
    session.add(
        Task(
            run_id=run.id, stage=Stage.STORYBOARD, provider="llm", status=TaskStatus.COMPLETED,
            input_hash=storyboard_key, idempotency_key=storyboard_key, cost=10,
        )
    )
    session.flush()

    scenes = []
    for idx in range(scene_count):
        scene = Scene(generation_run_id=run.id, scene_index=idx, script_text=f"scene {idx}")
        session.add(scene)
        session.flush()
        scenes.append(scene)

        for stage in (Stage.IMAGE, Stage.VIDEO, Stage.AUDIO):
            key = task_idempotency_key(run_id=run.id, stage=stage, scene_id=scene.id, input_version=str(scene.id))
            task = Task(
                run_id=run.id, scene_id=scene.id, stage=stage, provider="stub", status=TaskStatus.COMPLETED,
                input_hash=key, idempotency_key=key, cost=5,
            )
            session.add(task)
            session.flush()
            session.add(
                MediaAsset(
                    run_id=run.id, task_id=task.id, scene_id=scene.id, kind=_MEDIA_KIND_BY_STAGE[stage],
                    storage_key=f"stub/{task.id}", content_type="application/octet-stream", size_bytes=1,
                    checksum="", retention_class=RetentionClass.EPHEMERAL,
                )
            )
    session.commit()
    return user, run, scenes


async def test_partial_rerun_of_video_copies_sibling_audio_for_lipsync_join(db_session):
    user, run, scenes = _seed_completed_pipeline_up_to_lipsync(db_session)
    target_scene = scenes[0]
    other_scene = scenes[1]

    async with AsyncSessionLocal() as async_session:
        new_run = await request_partial_rerun(
            async_session, parent_run_id=run.id, stage=Stage.VIDEO, scene_id=target_scene.id, user_id=user.id,
        )

    new_tasks = db_session.query(Task).filter_by(run_id=new_run.id).all()
    new_scene = db_session.query(Scene).filter_by(generation_run_id=new_run.id, scene_index=target_scene.scene_index).one()
    new_other_scene = db_session.query(Scene).filter_by(generation_run_id=new_run.id, scene_index=other_scene.scene_index).one()

    # AUDIO предшественник target-сцены скопирован как COMPLETED — иначе LIPSYNC join
    # внутри new_run никогда не увидит его завершённым.
    audio_tasks = [t for t in new_tasks if t.stage == Stage.AUDIO and t.scene_id == new_scene.id]
    assert len(audio_tasks) == 1
    assert audio_tasks[0].status == TaskStatus.COMPLETED

    # Сама VIDEO-задача — новая, ждёт выполнения (пересчитывается этим partial rerun).
    video_tasks = [t for t in new_tasks if t.stage == Stage.VIDEO and t.scene_id == new_scene.id]
    assert len(video_tasks) == 1
    assert video_tasks[0].status == TaskStatus.PENDING

    # Сцена, НЕ участвующая в rerun, тоже получает свои IMAGE/VIDEO/AUDIO как COMPLETED —
    # иначе all-scenes join для COMPOSITION никогда не пройдёт по всему run.
    other_video = [t for t in new_tasks if t.stage == Stage.VIDEO and t.scene_id == new_other_scene.id]
    assert len(other_video) == 1
    assert other_video[0].status == TaskStatus.COMPLETED

    # MediaAsset скопированной AUDIO-задачи перенесён вместе с ней.
    audio_assets = db_session.query(MediaAsset).filter_by(task_id=audio_tasks[0].id).all()
    assert len(audio_assets) == 1
    assert audio_assets[0].scene_id == new_scene.id

    # Перенос завершённого контекста — не новая работа: не должно быть ни одной
    # CreditTransaction, привязанной к скопированным (уже COMPLETED) задачам.
    copied_task_ids = [t.id for t in new_tasks if t.status == TaskStatus.COMPLETED]
    charges = db_session.query(CreditTransaction).filter(CreditTransaction.task_id.in_(copied_task_ids)).all()
    assert charges == []


async def test_partial_rerun_of_storyboard_preserves_script_and_avoids_scene_index_collision(db_session):
    """STORYBOARD rerun инвалидирует всю раскадровку — Scene не копируются заранее
    (иначе новый _materialize_scenes_and_fanout столкнётся с UNIQUE(generation_run_id,
    scene_index)), а исходный script_text переносится в новую задачу."""
    user, run, scenes = _seed_completed_pipeline_up_to_lipsync(db_session, scene_count=2)
    storyboard_task = db_session.query(Task).filter_by(run_id=run.id, stage=Stage.STORYBOARD).one()
    storyboard_task.input_snapshot = {"script_text": "original creative script"}
    db_session.commit()

    async with AsyncSessionLocal() as async_session:
        new_run = await request_partial_rerun(
            async_session, parent_run_id=run.id, stage=Stage.STORYBOARD, scene_id=None, user_id=user.id,
        )

    new_scenes_before = db_session.query(Scene).filter_by(generation_run_id=new_run.id).all()
    assert new_scenes_before == []  # Scene не скопированы заранее

    new_storyboard_task = db_session.query(Task).filter_by(run_id=new_run.id, stage=Stage.STORYBOARD).one()
    assert new_storyboard_task.input_snapshot == {"script_text": "original creative script"}
    # Переводим в состояние, из которого complete_task вызывается в проде: задача
    # создаётся PENDING, а результат приходит уже из WAITING_PROVIDER.
    new_storyboard_task.status = TaskStatus.WAITING_PROVIDER
    db_session.commit()

    result = ProviderJobResult(
        provider_job_id=None,
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"scenes": [{"script_text": "s0"}, {"script_text": "s1"}]},),
    )
    # Не должно упасть на UNIQUE(generation_run_id, scene_index).
    complete_task(db_session, task_id=new_storyboard_task.id, result=result)

    new_scenes_after = db_session.query(Scene).filter_by(generation_run_id=new_run.id).order_by(Scene.scene_index).all()
    assert [s.scene_index for s in new_scenes_after] == [0, 1]
    assert [s.script_text for s in new_scenes_after] == ["s0", "s1"]
