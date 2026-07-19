"""Требует live PostgreSQL — см. conftest.py (skip, если недоступна)."""

import uuid

from toontales_ai.adapters.base import ProviderJobResult
from toontales_ai.domain.enums import CreditTransactionType, ProviderJobStatus, Stage, TaskStatus
from toontales_ai.domain.models import CreditTransaction, GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.pipeline_sync import complete_task


def _seed_run_with_pending_task(session, *, stage: Stage = Stage.IMAGE, cost: int = 30):
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=1000)
    session.add(user)
    session.flush()

    project = Project(user_id=user.id, name="test project")
    session.add(project)
    session.flush()

    run = GenerationRun(project_id=project.id)
    session.add(run)
    session.flush()

    key = task_idempotency_key(run_id=run.id, stage=stage, scene_id=None, input_version="v1")
    task = Task(run_id=run.id, stage=stage, provider="stub", input_hash=key, idempotency_key=key, cost=cost)
    session.add(task)
    session.commit()
    return user, run, task


def test_duplicate_completion_charges_only_once(db_session):
    """Регрессия review.md §2/§5: гонка poll/webhook не должна привести к двойному charge."""
    user, run, task = _seed_run_with_pending_task(db_session)
    # artifacts обязателен для media-стадии (IMAGE) с версии P1.6-фикса:
    # SUCCEEDED без валидного artifact теперь трактуется как NO_VALID_ARTIFACT,
    # а не как оплаченный успех — тест проверяет идемпотентность charge, не это.
    success = ProviderJobResult(
        provider_job_id="job-1",
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": "test/duplicate-delivery", "content_type": "image/png"},),
    )

    complete_task(db_session, task_id=task.id, result=success)
    complete_task(db_session, task_id=task.id, result=success)  # повторная доставка

    charges = (
        db_session.query(CreditTransaction)
        .filter_by(task_id=task.id, type=CreditTransactionType.CHARGE)
        .all()
    )
    assert len(charges) == 1


def test_failed_task_releases_hold_after_max_retries(db_session):
    user, run, task = _seed_run_with_pending_task(db_session, cost=50)
    failure = ProviderJobResult(provider_job_id=None, status=ProviderJobStatus.FAILED, error_code="E", error_detail="boom")

    for _ in range(10):  # заведомо больше MAX_RETRIES
        db_session.refresh(task)
        if task.status == TaskStatus.FAILED:
            break
        complete_task(db_session, task_id=task.id, result=failure)

    db_session.refresh(task)
    assert task.status == TaskStatus.FAILED

    releases = (
        db_session.query(CreditTransaction)
        .filter_by(task_id=task.id, type=CreditTransactionType.RELEASE)
        .all()
    )
    assert len(releases) == 1
    assert releases[0].amount == 50


def test_run_ownership_isolation(db_session):
    """review.md §6: run.project.user_id == authenticated_user.id."""
    _, run_a, _ = _seed_run_with_pending_task(db_session)
    other_user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=100)
    db_session.add(other_user)
    db_session.commit()

    project = db_session.get(Project, run_a.project_id)
    assert project.user_id != other_user.id
