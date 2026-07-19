"""Celery-задачи: submit провайдеру и polling. Только retry для классифицированных
transient-ошибок (review.md §7) — на Celery-уровне ретраится связь с провайдером,
на domain-уровне (pipeline_sync.complete_task) — retry_count/RETRY_SCHEDULED
для провайдер-репортед failure. Единый безопасный runner на задачу: свой event
loop и своя sync Session на каждый вызов (review.md §7 — не переиспользуется
между задачами)."""

import asyncio
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from celery import Task as CeleryTask
from sqlalchemy import select

from toontales_ai.adapters.base import ProviderJobResult, ProviderSubmission, StageInput
from toontales_ai.adapters.registry import get_adapter
from toontales_ai.domain.enums import MediaKind, ProviderJobStatus, Stage, TaskStatus
from toontales_ai.domain.models import MediaAsset, Scene, Task
from toontales_ai.orchestration.pipeline_sync import complete_task
from toontales_ai.storage.composition import CompositionError, SceneClip, compose_scenes
from toontales_ai.storage.db import SyncSessionLocal
from toontales_ai.storage.s3 import download_to_path, upload_from_path
from toontales_ai.workers.celery_app import celery_app

# Классы ошибок, которые считаются transient и подлежат Celery-level retry.
TRANSIENT_ERRORS = (ConnectionError, TimeoutError)

MAX_POLL_BACKOFF_SECONDS = 60


def _exponential_backoff(attempt: int, base: int = 2, cap: int = MAX_POLL_BACKOFF_SECONDS) -> int:
    return min(cap, base * (2**attempt))


def _run_composition(session, task: Task) -> ProviderSubmission:
    """Реальная FFmpeg-сборка (v2.md stage 6): скачивает per-scene клипы стадии
    LIPSYNC (канонический "финальный клип сцены" в DAG — см. STAGE_PREDECESSORS),
    склеивает и загружает результат обратно в S3. Требует реального object storage
    с уже загруженными артефактами — при stub-адаптерах (без реального S3) упадёт
    на скачивании, это ожидаемо до подключения настоящих provider-адаптеров."""
    scenes = session.execute(
        select(Scene).where(Scene.generation_run_id == task.run_id).order_by(Scene.scene_index)
    ).scalars().all()
    if not scenes:
        raise CompositionError(f"run {task.run_id} has no scenes to compose")

    with tempfile.TemporaryDirectory(prefix="toontales-compose-") as tmp:
        tmp_dir = Path(tmp)
        clips: list[SceneClip] = []
        for scene in scenes:
            asset = session.execute(
                select(MediaAsset)
                .join(Task, Task.id == MediaAsset.task_id)
                .where(
                    MediaAsset.scene_id == scene.id,
                    MediaAsset.kind == MediaKind.VIDEO,
                    Task.stage == Stage.LIPSYNC,
                )
                .order_by(MediaAsset.created_at.desc())
            ).scalars().first()
            if asset is None:
                raise CompositionError(f"no lipsync video asset for scene {scene.id}")

            local_path = tmp_dir / f"scene_{scene.scene_index}.mp4"
            download_to_path(asset.storage_key, local_path)
            clips.append(SceneClip(video_path=local_path))

        output_path = tmp_dir / "final.mp4"
        compose_scenes(clips, output_path=output_path)

        final_storage_key = f"runs/{task.run_id}/final_render/{task.id}.mp4"
        upload_from_path(output_path, final_storage_key, content_type="video/mp4")
        size_bytes = output_path.stat().st_size

    result = ProviderJobResult(
        provider_job_id=None,
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": final_storage_key, "content_type": "video/mp4", "size_bytes": size_bytes},),
    )
    return ProviderSubmission(provider_job_id=None, status=ProviderJobStatus.SUCCEEDED, result=result)


def _failed_submission(error_code: str, error_detail: str) -> ProviderSubmission:
    """Единая точка построения FAILED ProviderSubmission — используется и для
    доменных ошибок composition, и для любых прочих исключений во время submit,
    чтобы они шли через complete_task() и его retry_count/RETRY_SCHEDULED/release
    логику вместо того, чтобы утекать из Celery-задачи необработанными (P0-баг:
    раньше ловился только CompositionError, а botocore/OSError/FileNotFoundError
    оставляли Task навечно в SUBMITTING без release hold)."""
    return ProviderSubmission(
        provider_job_id=None,
        status=ProviderJobStatus.FAILED,
        result=ProviderJobResult(
            provider_job_id=None,
            status=ProviderJobStatus.FAILED,
            error_code=error_code,
            error_detail=error_detail,
        ),
    )


def _build_stage_input(session, task: Task) -> StageInput:
    payload: dict = {}
    if task.stage == Stage.STORYBOARD:
        payload = task.input_snapshot or {}
    elif task.scene_id is not None:
        scene = session.get(Scene, task.scene_id)
        if scene is not None:
            payload = {
                "script_text": scene.script_text,
                "image_prompt": scene.image_prompt,
                "camera_movement": scene.camera_movement,
                "mood_notes": scene.mood_notes,
            }
    return StageInput(task_id=str(task.id), scene_id=str(task.scene_id) if task.scene_id else None, payload=payload)


@celery_app.task(
    name="toontales_ai.workers.tasks.process_task",
    bind=True,
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=MAX_POLL_BACKOFF_SECONDS,
    retry_jitter=True,
    max_retries=5,
)
def process_task(self: CeleryTask, task_id: str) -> None:
    with SyncSessionLocal() as session:
        task = session.execute(select(Task).where(Task.id == uuid.UUID(task_id)).with_for_update()).scalar_one_or_none()
        if task is None or task.status not in (TaskStatus.PENDING, TaskStatus.RETRY_SCHEDULED):
            return  # уже обработан или больше не существует — идемпотентный no-op

        task.status = TaskStatus.SUBMITTING
        task.attempt_no += 1
        task.celery_task_id = self.request.id
        stage_input = _build_stage_input(session, task)
        session.commit()

        try:
            if task.stage == Stage.COMPOSITION:
                # Composition — локальный FFmpeg-слой, не внешний provider adapter (v2.md stage 6).
                try:
                    submission = _run_composition(session, task)
                except CompositionError as exc:
                    submission = _failed_submission("COMPOSITION_FAILED", str(exc))
            else:
                adapter = get_adapter(task.stage)
                submission = asyncio.run(adapter.submit(stage_input, idempotency_key=task.idempotency_key))
        except TRANSIENT_ERRORS:
            # Известная transient-ошибка (сеть/таймаут) — возвращаем Task в PENDING,
            # иначе Celery-level retry (autoretry_for) наткнётся на guard в начале
            # функции (status not in PENDING/RETRY_SCHEDULED), станет no-op'ом, и Task
            # навсегда останется в SUBMITTING (P0: retry механизм не мог фактически
            # повторить попытку после первого падения).
            task.status = TaskStatus.PENDING
            session.commit()
            raise
        except Exception as exc:
            # Любая иная ошибка (botocore/S3, отсутствующий ffmpeg, повреждённый файл
            # и т.п.) — не транзиентная в понимании Celery-level retry, но и не должна
            # оставлять Task в SUBMITTING навсегда (P0). Заворачиваем в тот же FAILED-путь,
            # что и CompositionError — дальше решает domain-level retry_count/release
            # в complete_task().
            submission = _failed_submission("TASK_EXECUTION_ERROR", str(exc))

    with SyncSessionLocal() as session:
        if submission.result is not None:
            complete_task(session, task_id=uuid.UUID(task_id), result=submission.result)
        else:
            task = session.execute(select(Task).where(Task.id == uuid.UUID(task_id)).with_for_update()).scalar_one()
            task.status = TaskStatus.WAITING_PROVIDER
            task.provider_job_id = submission.provider_job_id
            task.provider_status = submission.status
            task.next_poll_at = datetime.now(timezone.utc) + timedelta(seconds=_exponential_backoff(0))
            session.commit()
            poll_task.apply_async(args=[task_id], countdown=_exponential_backoff(0))
            return

    _maybe_retry_scheduled(self, task_id)


@celery_app.task(
    name="toontales_ai.workers.tasks.poll_task",
    bind=True,
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=MAX_POLL_BACKOFF_SECONDS,
    retry_jitter=True,
    max_retries=20,
)
def poll_task(self: CeleryTask, task_id: str) -> None:
    with SyncSessionLocal() as session:
        task = session.get(Task, uuid.UUID(task_id))
        if task is None or task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
            return
        if task.provider_job_id is None:
            return  # нечего опрашивать — submit ещё не завершился/провалился раньше

        adapter = get_adapter(task.stage)
        provider_job_id = task.provider_job_id
        poll_attempt = task.attempt_no

    result: ProviderJobResult = asyncio.run(adapter.poll(provider_job_id))

    if result.status in (ProviderJobStatus.QUEUED, ProviderJobStatus.PROCESSING):
        delay = result.retry_after_seconds or _exponential_backoff(poll_attempt)
        with SyncSessionLocal() as session:
            task = session.get(Task, uuid.UUID(task_id))
            task.next_poll_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            session.commit()
        poll_task.apply_async(args=[task_id], countdown=delay)
        return

    with SyncSessionLocal() as session:
        complete_task(session, task_id=uuid.UUID(task_id), result=result)

    _maybe_retry_scheduled(self, task_id)


def _maybe_retry_scheduled(self: CeleryTask, task_id: str) -> None:
    """После complete_task проверяем: если domain-уровень запросил повтор
    (RETRY_SCHEDULED, провайдер вернул FAILED, но retry_count не исчерпан) —
    переставляем process_task с backoff."""
    with SyncSessionLocal() as session:
        task = session.get(Task, uuid.UUID(task_id))
        if task is not None and task.status == TaskStatus.RETRY_SCHEDULED:
            delay = _exponential_backoff(task.retry_count)
            process_task.apply_async(args=[task_id], countdown=delay)
