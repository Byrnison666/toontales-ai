"""Периодические задачи: outbox dispatcher и reconciliation зависших Task
(review.md §10, пробел 'нет общего deadline/max polling age и reconciliation
waiting_provider после рестарта worker')."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from toontales_ai.domain.enums import TaskStatus
from toontales_ai.domain.models import Task
from toontales_ai.orchestration.outbox_dispatcher import dispatch_once
from toontales_ai.storage.db import SyncSessionLocal
from toontales_ai.workers.celery_app import celery_app

# Если Task завис в SUBMITTING дольше этого — process_task, скорее всего,
# упал после commit(SUBMITTING) до реального submit(); безопасно вернуть в PENDING.
STUCK_SUBMITTING_TIMEOUT = timedelta(minutes=5)

# Если WAITING_PROVIDER не получал новый next_poll_at дольше этого — запланированный
# poll_task, вероятно, был потерян при рестарте воркера; переставляем poll вручную.
STALE_WAITING_PROVIDER_GRACE = timedelta(minutes=10)

# Общий deadline: если Task не завершился за это время — принудительно failed + release.
MAX_TASK_AGE = timedelta(hours=2)


@celery_app.task(name="toontales_ai.workers.beat.dispatch_outbox")
def dispatch_outbox() -> int:
    with SyncSessionLocal() as session:
        return dispatch_once(session)


@celery_app.task(name="toontales_ai.workers.beat.reconcile_stale_tasks")
def reconcile_stale_tasks() -> None:
    from toontales_ai.orchestration.pipeline_sync import _release  # переиспользуем существующий helper
    from toontales_ai.workers.tasks import poll_task, process_task

    now = datetime.now(timezone.utc)

    with SyncSessionLocal() as session:
        stuck_submitting = session.execute(
            select(Task).where(Task.status == TaskStatus.SUBMITTING, Task.created_at < now - STUCK_SUBMITTING_TIMEOUT)
        ).scalars().all()
        for task in stuck_submitting:
            if now - task.created_at > MAX_TASK_AGE:
                task.status = TaskStatus.FAILED
                task.error_payload = {"code": "RECONCILE_TIMEOUT", "detail": "stuck in SUBMITTING past max task age"}
                _release(session, task)
            else:
                task.status = TaskStatus.PENDING
        session.commit()
        to_resubmit = [t.id for t in stuck_submitting if t.status == TaskStatus.PENDING]

    for task_id in to_resubmit:
        process_task.apply_async(args=[str(task_id)])

    with SyncSessionLocal() as session:
        stale_waiting = session.execute(
            select(Task).where(
                Task.status == TaskStatus.WAITING_PROVIDER,
                Task.next_poll_at < now - STALE_WAITING_PROVIDER_GRACE,
            )
        ).scalars().all()
        stale_ids = [t.id for t in stale_waiting]

        expired = session.execute(
            select(Task).where(
                Task.status.in_([TaskStatus.WAITING_PROVIDER, TaskStatus.PROCESSING]),
                Task.created_at < now - MAX_TASK_AGE,
            )
        ).scalars().all()
        for task in expired:
            task.status = TaskStatus.FAILED
            task.error_payload = {"code": "RECONCILE_TIMEOUT", "detail": "exceeded max task age"}
            _release(session, task)
        expired_ids = {t.id for t in expired}
        session.commit()

    for task_id in stale_ids:
        if task_id not in expired_ids:
            poll_task.apply_async(args=[str(task_id)])
