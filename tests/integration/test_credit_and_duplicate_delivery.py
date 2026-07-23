"""Требует live PostgreSQL — см. conftest.py (skip, если недоступна)."""

import uuid

from toontales_ai.adapters.base import ProviderJobResult
from toontales_ai.domain.enums import CreditTransactionType, ProviderJobStatus, RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import CreditTransaction, GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.pipeline_sync import _create_task_and_hold, _hold_and_enqueue, complete_task


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
    # WAITING_PROVIDER, а не PENDING: complete_task в проде вызывается только
    # когда задача ждёт результат провайдера (см. гард по статусу в pipeline_sync).
    task = Task(run_id=run.id, stage=stage, provider="stub", status=TaskStatus.WAITING_PROVIDER,
                provider_job_id="job-1",
                input_hash=key, idempotency_key=key, cost=cost)
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
        # В проде между провалами задача переотправляется (RETRY_SCHEDULED ->
        # ... -> WAITING_PROVIDER с новым job id). complete_task применяет
        # результат только к ждущей задаче, поэтому симулируем переотправку.
        if task.status == TaskStatus.RETRY_SCHEDULED:
            task.status = TaskStatus.WAITING_PROVIDER
            db_session.commit()
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


def test_hold_and_enqueue_actually_deducts_balance(db_session):
    """P0, найдено живым e2e-прогоном (FastAPI+Celery worker+Postgres): _hold_and_enqueue
    (используется для всех стадий после самой первой STORYBOARD-задачи run) создавала
    CreditTransaction(HOLD), но никогда не уменьшала user.credit_balance. В проде это
    означало, что ни одна стадия после storyboard не была реально оплачена, а release
    при её падении НАЧИСЛЯЛ деньги, которые никогда не списывались."""
    user, run, _ = _seed_run_with_pending_task(db_session)
    balance_before = user.credit_balance

    key = task_idempotency_key(run_id=run.id, stage=Stage.IMAGE, scene_id=None, input_version="v2")
    task_id = _create_task_and_hold(db_session, run_id=run.id, stage=Stage.IMAGE, scene_id=None, key=key, cost=40)
    _hold_and_enqueue(db_session, task_id=task_id, run_id=run.id, cost=40)
    db_session.commit()

    db_session.refresh(user)
    assert user.credit_balance == balance_before - 40

    # Повторный вызов (эмулирует гонку двух join-веток на _advance) не должен
    # списать повторно — ON CONFLICT DO NOTHING на CreditTransaction защищает и hold,
    # и списание баланса от задваивания.
    _hold_and_enqueue(db_session, task_id=task_id, run_id=run.id, cost=40)
    db_session.commit()
    db_session.refresh(user)
    assert user.credit_balance == balance_before - 40

    # Провал задачи после MAX_RETRIES должен вернуть баланс РОВНО к исходному —
    # не больше (это и был баг: release добавлял деньги, которые не списывались).
    failure = ProviderJobResult(provider_job_id=None, status=ProviderJobStatus.FAILED, error_code="E", error_detail="boom")
    for _ in range(10):
        db_session.refresh(user)
        task = db_session.get(Task, task_id)
        if task.status == TaskStatus.FAILED:
            break
        # complete_task применяет результат только к ждущей задаче: задача создана
        # PENDING, а в проде провал приходит из WAITING_PROVIDER (после submit),
        # и между ретраями идёт переотправка. Симулируем это.
        if task.status in (TaskStatus.PENDING, TaskStatus.RETRY_SCHEDULED):
            task.status = TaskStatus.WAITING_PROVIDER
            db_session.commit()
        complete_task(db_session, task_id=task_id, result=failure)

    db_session.refresh(user)
    assert user.credit_balance == balance_before


def test_hold_and_enqueue_fails_task_explicitly_when_balance_insufficient(db_session):
    """P0 (аудит финансовой корректности): раньше _hold_and_enqueue не проверяла
    достаточность баланса перед списанием — decrement уходил в CheckConstraint
    ("credit_balance >= 0") на уровне Postgres, IntegrityError не входит в
    TRANSIENT_ERRORS воркера, вся транзакция complete_task() откатывалась
    (включая только что выставленный COMPLETED статус ПРЕДЫДУЩЕЙ стадии), а
    Celery-задача падала необработанной — run зависал в RUNNING навсегда без
    сигнала пользователю. Теперь — явный FAILED Task/Run вместо тихого зависания."""
    user, run, _ = _seed_run_with_pending_task(db_session)
    user.credit_balance = 10
    db_session.commit()

    key = task_idempotency_key(run_id=run.id, stage=Stage.VIDEO, scene_id=None, input_version="v3")
    task_id = _create_task_and_hold(db_session, run_id=run.id, stage=Stage.VIDEO, scene_id=None, key=key, cost=200)
    _hold_and_enqueue(db_session, task_id=task_id, run_id=run.id, cost=200)
    db_session.commit()  # не должно бросить IntegrityError

    task = db_session.get(Task, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.error_payload["code"] == "INSUFFICIENT_CREDITS"

    db_session.refresh(run)
    assert run.status == RunStatus.FAILED

    db_session.refresh(user)
    assert user.credit_balance == 10  # баланс не тронут — hold не состоялся

    holds = (
        db_session.query(CreditTransaction)
        .filter_by(task_id=task_id, type=CreditTransactionType.HOLD)
        .all()
    )
    assert holds == []  # CreditTransaction(HOLD) не создавалась для непрошедшей проверки


def test_run_ownership_isolation(db_session):
    """review.md §6: run.project.user_id == authenticated_user.id."""
    _, run_a, _ = _seed_run_with_pending_task(db_session)
    other_user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=100)
    db_session.add(other_user)
    db_session.commit()

    project = db_session.get(Project, run_a.project_id)
    assert project.user_id != other_user.id
