"""Прайсинг v3: одно списание за ролик на успешной COMPOSITION, ничего на провале,
идемпотентность повторной доставки. Резерва и per-task денег больше нет.

Требует live PostgreSQL (skip, если недоступна) — см. conftest.py."""

import uuid

from toontales_ai.adapters.base import ProviderJobResult
from toontales_ai.domain.enums import CreditTransactionType, ProviderJobStatus, RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import CreditTransaction, GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.pipeline_sync import _charge_run, complete_task


def _seed(session, *, balance: int, price: int):
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=balance)
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()
    run = GenerationRun(project_id=project.id, status=RunStatus.RUNNING, duration_seconds=30, price=price)
    session.add(run)
    session.commit()
    return user, run


def _charges(session, run_id):
    return session.query(CreditTransaction).filter_by(run_id=run_id, type=CreditTransactionType.CHARGE).all()


def test_charge_run_deducts_price_once_and_records_ledger(db_session):
    user, run = _seed(db_session, balance=5000, price=3170)

    _charge_run(db_session, run)
    db_session.commit()
    db_session.refresh(user)

    assert user.credit_balance == 5000 - 3170
    charges = _charges(db_session, run.id)
    assert [c.amount for c in charges] == [3170]
    assert charges[0].task_id is None  # списание на уровне run, не задачи


def test_charge_run_is_idempotent(db_session):
    """Повторная доставка COMPOSITION-колбэка не должна списать дважды."""
    user, run = _seed(db_session, balance=5000, price=3170)

    _charge_run(db_session, run)
    db_session.commit()
    _charge_run(db_session, run)
    db_session.commit()
    db_session.refresh(user)

    assert user.credit_balance == 5000 - 3170
    assert len(_charges(db_session, run.id)) == 1


def test_free_run_charges_nothing(db_session):
    """price=0 (partial rerun) — списывать нечего."""
    user, run = _seed(db_session, balance=5000, price=0)

    _charge_run(db_session, run)
    db_session.commit()
    db_session.refresh(user)

    assert user.credit_balance == 5000
    assert _charges(db_session, run.id) == []


def test_charge_capped_by_balance_keeps_ledger_consistent(db_session):
    """Недобор (баланс просел мимо start-проверки, напр. правкой админа): списываем
    сколько есть и записываем ФАКТ, чтобы баланс сходился с ledger. Не обрываем."""
    user, run = _seed(db_session, balance=1000, price=3170)

    _charge_run(db_session, run)
    db_session.commit()
    db_session.refresh(user)

    assert user.credit_balance == 0
    charges = _charges(db_session, run.id)
    assert [c.amount for c in charges] == [1000]  # записана фактически списанная сумма


def _composition_task(session, run):
    key = task_idempotency_key(run_id=run.id, stage=Stage.COMPOSITION, scene_id=None, input_version="v1")
    task = Task(
        run_id=run.id, stage=Stage.COMPOSITION, provider="ffmpeg", status=TaskStatus.WAITING_PROVIDER,
        input_hash=key, idempotency_key=key,
    )
    session.add(task)
    session.commit()
    return task


def test_composition_success_completes_run_and_charges(db_session):
    user, run = _seed(db_session, balance=5000, price=3170)
    task = _composition_task(db_session, run)
    success = ProviderJobResult(
        provider_job_id=None,
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": "runs/x/final.mp4", "content_type": "video/mp4"},),
    )

    complete_task(db_session, task_id=task.id, result=success)
    db_session.refresh(run)
    db_session.refresh(user)

    assert run.status == RunStatus.COMPLETED
    assert user.credit_balance == 5000 - 3170
    assert len(_charges(db_session, run.id)) == 1

    # повторная доставка того же успеха — задача терминальна, повторно не спишет
    complete_task(db_session, task_id=task.id, result=success)
    db_session.refresh(user)
    assert user.credit_balance == 5000 - 3170
    assert len(_charges(db_session, run.id)) == 1


def test_composition_failure_charges_nothing(db_session):
    user, run = _seed(db_session, balance=5000, price=3170)
    task = _composition_task(db_session, run)
    failure = ProviderJobResult(provider_job_id=None, status=ProviderJobStatus.FAILED, error_code="E", error_detail="boom")

    for _ in range(10):
        db_session.refresh(task)
        if task.status == TaskStatus.FAILED:
            break
        if task.status == TaskStatus.RETRY_SCHEDULED:
            task.status = TaskStatus.WAITING_PROVIDER
            db_session.commit()
        complete_task(db_session, task_id=task.id, result=failure)

    db_session.refresh(user)
    db_session.refresh(run)
    assert run.status == RunStatus.FAILED
    assert user.credit_balance == 5000  # ничего не списано — на старте баланс не трогали
    assert _charges(db_session, run.id) == []
