"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.

Регрессия: GenerationRun.status раньше никогда не менялся с RUNNING — найдено
живым e2e-прогоном (FastAPI + Celery worker), где run.status оставался "running"
даже после успешного завершения всего пайплайна вплоть до COMPOSITION."""

import uuid

from toontales_ai.adapters.base import ProviderJobResult
from toontales_ai.domain.enums import ProviderJobStatus, RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.pipeline_sync import complete_task


def _seed_run_with_task(session, *, stage: Stage, cost: int = 10):
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=1000)
    session.add(user)
    session.flush()

    project = Project(user_id=user.id, name="p")
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


def test_composition_completion_marks_run_completed(db_session):
    user, run, task = _seed_run_with_task(db_session, stage=Stage.COMPOSITION)
    success = ProviderJobResult(
        provider_job_id=None,
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": "runs/x/final.mp4", "content_type": "video/mp4"},),
    )

    complete_task(db_session, task_id=task.id, result=success)

    db_session.refresh(run)
    assert run.status == RunStatus.COMPLETED
    assert run.finished_at is not None


def test_permanent_task_failure_marks_run_failed(db_session):
    user, run, task = _seed_run_with_task(db_session, stage=Stage.IMAGE, cost=30)
    failure = ProviderJobResult(provider_job_id=None, status=ProviderJobStatus.FAILED, error_code="E", error_detail="boom")

    for _ in range(10):
        db_session.refresh(task)
        if task.status == TaskStatus.FAILED:
            break
        complete_task(db_session, task_id=task.id, result=failure)

    db_session.refresh(run)
    assert run.status == RunStatus.FAILED
    assert run.finished_at is not None


def test_success_clears_stale_error_payload_from_prior_retries(db_session):
    """Ретраи оставляют error_payload на Task; финальный успех не должен показывать
    клиенту ошибку от предыдущей неудачной попытки как текущее состояние."""
    user, run, task = _seed_run_with_task(db_session, stage=Stage.IMAGE, cost=30)
    failure = ProviderJobResult(provider_job_id=None, status=ProviderJobStatus.FAILED, error_code="E", error_detail="transient")
    complete_task(db_session, task_id=task.id, result=failure)  # -> RETRY_SCHEDULED, error_payload set

    db_session.refresh(task)
    assert task.error_payload is not None

    success = ProviderJobResult(
        provider_job_id=None,
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": "test/recovered", "content_type": "image/png"},),
    )
    complete_task(db_session, task_id=task.id, result=success)

    db_session.refresh(task)
    assert task.status == TaskStatus.COMPLETED
    assert task.error_payload is None
