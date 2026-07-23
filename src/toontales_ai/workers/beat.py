"""Периодические задачи: outbox dispatcher и reconciliation зависших Task
(review.md §10, пробел 'нет общего deadline/max polling age и reconciliation
waiting_provider после рестарта worker')."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from toontales_ai.domain.enums import TaskStatus
from toontales_ai.domain.models import Task
from toontales_ai.observability import metrics
from toontales_ai.orchestration import provider_semaphore
from toontales_ai.orchestration.outbox_dispatcher import dispatch_once
from toontales_ai.storage.db import SyncSessionLocal
from toontales_ai.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Если Task завис в SUBMITTING дольше этого — process_task, скорее всего,
# упал после commit(SUBMITTING) до реального submit(); безопасно вернуть в PENDING.
STUCK_SUBMITTING_TIMEOUT = timedelta(minutes=5)

# Если WAITING_PROVIDER не получал новый next_poll_at дольше этого — запланированный
# poll_task, вероятно, был потерян при рестарте воркера; переставляем poll вручную.
STALE_WAITING_PROVIDER_GRACE = timedelta(minutes=10)

# Общий deadline: если Task не завершился за это время — принудительно failed + release.
MAX_TASK_AGE = timedelta(hours=2)

# P0, найдено живым e2e-прогоном (Sync.so concurrency_limit=1 → постоянные 429):
# TRANSIENT_ERRORS-ветка process_task возвращает Task в PENDING и re-raise'ит для
# Celery-level autoretry_for. Пока autoretry укладывается в свой max_retries — всё
# штатно. Но когда Celery ИСЧЕРПЫВАЕТ max_retries, он не перепланирует process_task
# снова, а Task остаётся в PENDING без единого запланированного Celery job — это
# отличается от "свежесозданного" PENDING (ещё не подхваченного dispatch_outbox)
# только по attempt_no > 0 (инкрементируется в начале process_task при каждом
# фактическом запуске). Без этой ветки такой Task зависает навсегда.
ORPHANED_PENDING_GRACE = timedelta(minutes=5)


@celery_app.task(name="toontales_ai.workers.beat.dispatch_outbox")
def dispatch_outbox() -> int:
    with SyncSessionLocal() as session:
        return dispatch_once(session)


@celery_app.task(name="toontales_ai.workers.beat.reconcile_stale_tasks")
def reconcile_stale_tasks() -> None:
    from toontales_ai.workers.tasks import poll_task, process_task

    # aware UTC для читаемости логов/error_payload; для сравнений с БД используется
    # только "now - timedelta" ВНУТРИ SQL WHERE (см. ниже) — SQL-side датой-арифметика
    # против TIMESTAMP WITHOUT TIME ZONE колонок стабильна независимо от TimeZone
    # сессии. Python-side "now - task.created_at" на УЖЕ round-trip'нутом из БД
    # значении — нет: обнаружено флакующим тестом, конкретное pooled-соединение
    # может вернуть created_at со сдвигом на TimeZone сессии (Europe/Moscow в этом
    # окружении) относительно aware/naive UTC `now`, вычисленного в Python. Поэтому
    # обе "старше MAX_TASK_AGE?" проверки (stuck_submitting и orphaned_pending)
    # переписаны как отдельные SQL-запросы вместо Python-side вычитания.
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with SyncSessionLocal() as session:
        # FOR UPDATE обязателен: без блокировки reconciler мог прочитать задачу,
        # параллельный complete_task успел бы её завершить и settle-нуть, а затем
        # reconciler перезаписал бы статус в FAILED и вернул полный холд поверх
        # частичного возврата. Под блокировкой Postgres перечитывает WHERE, и уже
        # завершённая задача в выборку не попадает. skip_locked — чтобы beat не
        # блокировался на задаче, которую прямо сейчас завершает воркер (реально
        # застрявшая в SUBMITTING никем не залочена, так что не пропускается).
        #
        # Граница MAX_TASK_AGE считается в SQL, а не в Python: round-trip'нутый из
        # БД created_at может съехать на TimeZone сессии относительно aware/naive
        # UTC now (см. развёрнутый комментарий выше) — Python-side вычитание тут
        # флакует, поэтому две выборки с SQL-арифметикой вместо одной.
        stuck_submitting_recoverable = session.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.SUBMITTING,
                Task.created_at < now - STUCK_SUBMITTING_TIMEOUT,
                Task.created_at >= now - MAX_TASK_AGE,
            )
            .with_for_update(skip_locked=True)
        ).scalars().all()
        stuck_submitting_expired = session.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.SUBMITTING,
                Task.created_at < now - STUCK_SUBMITTING_TIMEOUT,
                Task.created_at < now - MAX_TASK_AGE,
            )
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for task in stuck_submitting_expired:
            task.status = TaskStatus.FAILED
            task.error_payload = {"code": "RECONCILE_TIMEOUT", "detail": "stuck in SUBMITTING past max task age"}
            # прайсинг v3: возврата нет — на старте баланс не трогали
        for task in stuck_submitting_recoverable:
            task.status = TaskStatus.PENDING
        session.commit()
        to_resubmit = [task.id for task in stuck_submitting_recoverable]

    for task_id in to_resubmit:
        process_task.apply_async(args=[str(task_id)])
    if to_resubmit:
        logger.warning("stuck submitting tasks recovered", extra={"count": len(to_resubmit)})
        metrics.RECONCILED_TASKS_TOTAL.labels(reconciliation_type="stuck_submitting").inc(len(to_resubmit))

    with SyncSessionLocal() as session:
        # FOR UPDATE — по той же причине, что и выше: не дать reconciler-у затереть
        # статус задачи, которую параллельно завершает complete_task. Граница
        # MAX_TASK_AGE снова в SQL из-за таймзонного съезда created_at.
        orphaned_pending_recoverable = session.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.PENDING,
                Task.attempt_no > 0,
                Task.created_at < now - ORPHANED_PENDING_GRACE,
                Task.created_at >= now - MAX_TASK_AGE,
            )
            .with_for_update(skip_locked=True)
        ).scalars().all()
        orphaned_pending_expired = session.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.PENDING,
                Task.attempt_no > 0,
                Task.created_at < now - ORPHANED_PENDING_GRACE,
                Task.created_at < now - MAX_TASK_AGE,
            )
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for task in orphaned_pending_expired:
            task.status = TaskStatus.FAILED
            task.error_payload = {"code": "RECONCILE_TIMEOUT", "detail": "orphaned in PENDING past max task age"}
            # прайсинг v3: возврата нет — на старте баланс не трогали
        session.commit()
        orphaned_ids = [task.id for task in orphaned_pending_recoverable]

    for task_id in orphaned_ids:
        process_task.apply_async(args=[str(task_id)])
    if orphaned_ids:
        logger.warning("orphaned pending tasks recovered", extra={"count": len(orphaned_ids)})
        metrics.RECONCILED_TASKS_TOTAL.labels(reconciliation_type="orphaned_pending").inc(len(orphaned_ids))

    with SyncSessionLocal() as session:
        stale_waiting = session.execute(
            select(Task).where(
                Task.status == TaskStatus.WAITING_PROVIDER,
                Task.next_poll_at < now - STALE_WAITING_PROVIDER_GRACE,
            )
        ).scalars().all()
        stale_ids = [t.id for t in stale_waiting]

        expired = session.execute(
            select(Task)
            .where(
                Task.status.in_([TaskStatus.WAITING_PROVIDER, TaskStatus.PROCESSING]),
                Task.created_at < now - MAX_TASK_AGE,
            )
            # FOR UPDATE: эта ветка помечает FAILED и возвращает холд — её нельзя
            # выполнять на задаче, которую параллельно завершает complete_task.
            .with_for_update(skip_locked=True)
        ).scalars().all()
        # (task_id, stage) для освобождения provider-семафора ПОСЛЕ commit —
        # reconcile помечает FAILED в обход complete_task/tasks.py, где обычно
        # происходит release_slot; без этого слот lipsync-задачи держался бы до
        # TTL (admission-control-ревью).
        expired_semaphore_holders: list[tuple[str, "object"]] = []
        for task in expired:
            task.status = TaskStatus.FAILED
            task.error_payload = {"code": "RECONCILE_TIMEOUT", "detail": "exceeded max task age"}
            # прайсинг v3: возврата нет — на старте баланс не трогали
            if task.stage in provider_semaphore.SEMAPHORE_PROVIDER_BY_STAGE:
                expired_semaphore_holders.append((str(task.id), task.stage))
        expired_ids = {t.id for t in expired}
        session.commit()

    for holder, stage in expired_semaphore_holders:
        provider_semaphore.release_slot(
            provider=provider_semaphore.SEMAPHORE_PROVIDER_BY_STAGE[stage], holder=holder
        )

    stale_to_poll = [task_id for task_id in stale_ids if task_id not in expired_ids]
    for task_id in stale_to_poll:
        poll_task.apply_async(args=[str(task_id)])
    if stale_to_poll:
        logger.info("stale waiting provider tasks recovered", extra={"count": len(stale_to_poll)})
    if expired:
        logger.warning("expired tasks failed", extra={"count": len(expired)})
        metrics.RECONCILED_TASKS_TOTAL.labels(reconciliation_type="expired").inc(len(expired))
