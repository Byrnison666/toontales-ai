"""Celery-задачи: submit провайдеру и polling. Только retry для классифицированных
transient-ошибок (review.md §7) — на Celery-уровне ретраится связь с провайдером,
на domain-уровне (pipeline_sync.complete_task) — retry_count/RETRY_SCHEDULED
для провайдер-репортед failure. Единый безопасный runner на задачу: свой event
loop и своя sync Session на каждый вызов (review.md §7 — не переиспользуется
между задачами)."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from celery import Task as CeleryTask
from celery.exceptions import Retry
from sqlalchemy import select

from toontales_ai.adapters.base import ProviderJobResult, StageInput
from toontales_ai.adapters.registry import get_adapter
from toontales_ai.domain.enums import ProviderJobStatus, Stage, TaskStatus
from toontales_ai.domain.models import Scene, Task
from toontales_ai.orchestration.pipeline_sync import complete_task
from toontales_ai.storage.db import SyncSessionLocal
from toontales_ai.workers.celery_app import celery_app

# Классы ошибок, которые считаются transient и подлежат Celery-level retry.
TRANSIENT_ERRORS = (ConnectionError, TimeoutError)

MAX_POLL_BACKOFF_SECONDS = 60


def _exponential_backoff(attempt: int, base: int = 2, cap: int = MAX_POLL_BACKOFF_SECONDS) -> int:
    return min(cap, base * (2**attempt))


def _run_composition_stub(stage_input: StageInput):
    from toontales_ai.adapters.base import ProviderSubmission

    result = ProviderJobResult(
        provider_job_id=None,
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": f"stub/final/{stage_input.task_id}", "content_type": "video/mp4"},),
    )
    return ProviderSubmission(provider_job_id=None, status=ProviderJobStatus.SUCCEEDED, result=result)


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

        if task.stage == Stage.COMPOSITION:
            # Composition — локальный FFmpeg-слой, не внешний provider adapter
            # (v2.md stage 6). Реальная сборка FFmpeg вне объёма текущего шага —
            # заглушка эмулирует немедленный успех для сквозной прогонки пайплайна.
            submission = _run_composition_stub(stage_input)
        else:
            adapter = get_adapter(task.stage)
            submission = asyncio.run(adapter.submit(stage_input, idempotency_key=task.idempotency_key))

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
