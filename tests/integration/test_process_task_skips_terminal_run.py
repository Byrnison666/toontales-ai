"""Регрессия (ревью денежных путей): reconciler может провалить GenerationRun
(_fail_run_of), пока прочие его задачи ещё PENDING. process_task не должен
отправлять такую задачу провайдеру — иначе Runway/ElevenLabs расходы на
проваленном ролике идут впустую (списание только по успеху COMPOSITION)."""

import uuid
from unittest.mock import patch

from toontales_ai.domain.enums import RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.workers import tasks as tasks_module


class _NonClosingSession:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def _seed(session, *, run_status: RunStatus) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=10_000)
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()
    run = GenerationRun(project_id=project.id, status=run_status, duration_seconds=30, price=3170)
    session.add(run)
    session.flush()
    key = task_idempotency_key(run_id=run.id, stage=Stage.IMAGE, scene_id=None, input_version="v1")
    task = Task(
        run_id=run.id, stage=Stage.IMAGE, provider="stub", status=TaskStatus.PENDING,
        input_hash=key, idempotency_key=key,
    )
    session.add(task)
    session.commit()
    return task


def test_process_task_cancels_task_of_failed_run_without_submitting(db_session):
    task = _seed(db_session, run_status=RunStatus.FAILED)

    with patch.object(tasks_module, "SyncSessionLocal", return_value=_NonClosingSession(db_session)), \
         patch.object(tasks_module, "get_adapter") as mock_get_adapter:
        tasks_module.process_task.apply(args=[str(task.id)])

    # провайдер не запрашивался — задача терминализована до admission control
    mock_get_adapter.assert_not_called()
    db_session.refresh(task)
    assert task.status == TaskStatus.CANCELED
    assert task.error_payload["code"] == "RUN_TERMINAL"


def test_process_task_proceeds_for_running_run(db_session):
    """Контроль: у активного (RUNNING) run задача НЕ отсекается этим гардом —
    доходит до обычной обработки (адаптер запрашивается)."""
    task = _seed(db_session, run_status=RunStatus.RUNNING)

    with patch.object(tasks_module, "SyncSessionLocal", return_value=_NonClosingSession(db_session)), \
         patch.object(tasks_module, "get_adapter", side_effect=RuntimeError("stop after guard")) as mock_get_adapter:
        # ошибку глотаем — важно лишь, что гард не отсёк и дошло до get_adapter
        try:
            tasks_module.process_task.apply(args=[str(task.id)])
        except Exception:
            pass

    mock_get_adapter.assert_called()
    db_session.refresh(task)
    assert task.status != TaskStatus.CANCELED
