"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.

Регрессия: process_task ловит TRANSIENT_ERRORS, возвращает Task в PENDING и
re-raise'ит для Celery-level autoretry_for. Пока Celery не исчерпал max_retries —
он сам перепланирует process_task. Но когда max_retries исчерпан (напр. провайдер
стабильно отдаёт 429 дольше окна retry), Task остаётся в PENDING без единого
запланированного Celery job — найдено живым e2e-прогоном (Sync.so
concurrency_limit=1). reconcile_stale_tasks должен подхватывать такие Task и
requeue'ить их снова, а не только SUBMITTING/WAITING_PROVIDER."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from toontales_ai.domain.enums import Stage, TaskStatus
from toontales_ai.domain.models import GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.workers import beat as beat_module


class _NonClosingSession:
    """reconcile_stale_tasks открывает несколько `with SyncSessionLocal() as session:`
    блоков подряд — реальный Session.__exit__ закрывает сессию после первого же
    блока (Python ищет __enter__/__exit__ на классе, инстанс-monkeypatch не
    перехватывается `with`). Обёртка отдаёт один и тот же test db_session и
    игнорирует close() между блоками."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def _seed_run(session) -> GenerationRun:
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=10_000)
    session.add(user)
    session.flush()

    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()

    run = GenerationRun(project_id=project.id)
    session.add(run)
    session.flush()
    return run


def test_reconcile_requeues_orphaned_pending_task_with_prior_attempts(db_session):
    run = _seed_run(db_session)
    key = task_idempotency_key(run_id=run.id, stage=Stage.LIPSYNC, scene_id=None, input_version="v1")
    task = Task(
        run_id=run.id, stage=Stage.LIPSYNC, provider="sync", status=TaskStatus.PENDING,
        attempt_no=6, input_hash=key, idempotency_key=key, cost=20,
    )
    db_session.add(task)
    db_session.commit()
    # created_at имеет server_default=func.now() — вручную отодвигаем в прошлое,
    # чтобы задача попала за ORPHANED_PENDING_GRACE.
    db_session.execute(
        Task.__table__.update().where(Task.id == task.id).values(
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - beat_module.ORPHANED_PENDING_GRACE - timedelta(minutes=1)
        )
    )
    db_session.commit()

    with patch.object(beat_module, "SyncSessionLocal", return_value=_NonClosingSession(db_session)), \
         patch("toontales_ai.workers.tasks.process_task") as mock_process_task, \
         patch("toontales_ai.workers.tasks.poll_task"):
        beat_module.reconcile_stale_tasks()

    mock_process_task.apply_async.assert_called_once_with(args=[str(task.id)])

    db_session.refresh(task)
    assert task.status == TaskStatus.PENDING  # ещё не FAILED — не старше MAX_TASK_AGE


def test_reconcile_ignores_freshly_created_pending_task(db_session):
    """attempt_no=0 — задача ещё ни разу не подхватывалась process_task, это
    нормальное ожидание первого dispatch_outbox, не orphan."""
    run = _seed_run(db_session)
    key = task_idempotency_key(run_id=run.id, stage=Stage.LIPSYNC, scene_id=None, input_version="v1")
    task = Task(
        run_id=run.id, stage=Stage.LIPSYNC, provider="sync", status=TaskStatus.PENDING,
        attempt_no=0, input_hash=key, idempotency_key=key, cost=20,
    )
    db_session.add(task)
    db_session.commit()
    db_session.execute(
        Task.__table__.update().where(Task.id == task.id).values(
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - beat_module.ORPHANED_PENDING_GRACE - timedelta(minutes=1)
        )
    )
    db_session.commit()

    with patch.object(beat_module, "SyncSessionLocal", return_value=_NonClosingSession(db_session)), \
         patch("toontales_ai.workers.tasks.process_task") as mock_process_task, \
         patch("toontales_ai.workers.tasks.poll_task"):
        beat_module.reconcile_stale_tasks()

    mock_process_task.apply_async.assert_not_called()


def test_reconcile_fails_orphaned_pending_past_max_task_age(db_session):
    run = _seed_run(db_session)
    key = task_idempotency_key(run_id=run.id, stage=Stage.LIPSYNC, scene_id=None, input_version="v1")
    task = Task(
        run_id=run.id, stage=Stage.LIPSYNC, provider="sync", status=TaskStatus.PENDING,
        attempt_no=6, input_hash=key, idempotency_key=key, cost=20,
    )
    db_session.add(task)
    db_session.commit()
    db_session.execute(
        Task.__table__.update().where(Task.id == task.id).values(
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - beat_module.MAX_TASK_AGE - timedelta(minutes=1)
        )
    )
    db_session.commit()

    with patch.object(beat_module, "SyncSessionLocal", return_value=_NonClosingSession(db_session)), \
         patch("toontales_ai.workers.tasks.process_task") as mock_process_task, \
         patch("toontales_ai.workers.tasks.poll_task"):
        beat_module.reconcile_stale_tasks()

    mock_process_task.apply_async.assert_not_called()

    db_session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert task.error_payload["code"] == "RECONCILE_TIMEOUT"
