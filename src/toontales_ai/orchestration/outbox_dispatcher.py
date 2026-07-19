"""Единственное место, вызывающее celery.send_task(). Опрашивает pipeline_outbox
и публикует задачи at-least-once (Codex-ревью §pipeline_manager, review.md §10:
transactional outbox вместо прямого enqueue внутри бизнес-транзакции)."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from toontales_ai.domain.enums import OutboxStatus
from toontales_ai.domain.models import PipelineOutbox

LEASE_SECONDS = 30
BATCH_SIZE = 100


def claim_batch(session: Session) -> list[PipelineOutbox]:
    now = datetime.now(timezone.utc)
    rows = session.execute(
        select(PipelineOutbox)
        .where(
            PipelineOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.PUBLISHING]),
            PipelineOutbox.available_at <= now,
        )
        .where((PipelineOutbox.lease_until.is_(None)) | (PipelineOutbox.lease_until < now))
        .order_by(PipelineOutbox.available_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    ).scalars().all()

    for row in rows:
        row.status = OutboxStatus.PUBLISHING
        row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        row.attempts += 1
    session.commit()
    return list(rows)


def mark_published(session: Session, outbox_id: uuid.UUID) -> None:
    row = session.get(PipelineOutbox, outbox_id)
    if row is None:
        return
    row.status = OutboxStatus.PUBLISHED
    row.published_at = datetime.now(timezone.utc)
    session.commit()


def dispatch_once(session: Session) -> int:
    """Забирает лот outbox-событий и публикует их в Celery. At-least-once:
    если процесс упадёт между send_task и mark_published, событие переотправится
    после истечения lease — обработчик Celery-задачи обязан быть идемпотентным
    (перечитывает Task по id и делает no-op, если тот уже terminal)."""
    from toontales_ai.workers.celery_app import celery_app

    rows = claim_batch(session)
    for row in rows:
        celery_app.send_task(
            "toontales_ai.workers.tasks.process_task",
            args=[str(row.aggregate_id)],
            task_id=str(row.id),
        )
        mark_published(session, row.id)
    return len(rows)
