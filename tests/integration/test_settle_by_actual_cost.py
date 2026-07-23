"""Списание по фактической себестоимости, а не по холду.

Требует live PostgreSQL — см. conftest.py (skip, если недоступна)."""

import uuid

from toontales_ai.adapters.base import ProviderJobResult
from toontales_ai.domain.enums import CreditTransactionType, ProviderJobStatus, Stage
from toontales_ai.domain.models import CreditTransaction, GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.pipeline_sync import complete_task
from toontales_ai.orchestration.pricing import price_sparks, stage_hold


def _seed_task(session, *, stage: Stage, balance: int = 100_000):
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=balance)
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="test project")
    session.add(project)
    session.flush()
    run = GenerationRun(project_id=project.id)
    session.add(run)
    session.flush()

    hold = stage_hold(stage)
    key = task_idempotency_key(run_id=run.id, stage=stage, scene_id=None, input_version="v1")
    task = Task(run_id=run.id, stage=stage, provider="stub", input_hash=key, idempotency_key=key, cost=hold)
    session.add(task)
    # Холд уже списан с баланса на этапе _hold_and_enqueue — воспроизводим это,
    # иначе возврат остатка проверялся бы от неправильной базы.
    user.credit_balance -= hold
    session.commit()
    return user, task


def _image_success(duration_seconds=None) -> ProviderJobResult:
    usage = {"images": 1} if duration_seconds is None else {"duration_seconds": duration_seconds}
    return ProviderJobResult(
        provider_job_id="job-1",
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": "test/settle", "content_type": "image/png"},),
        usage=usage,
    )


def _ledger(session, task_id, tx_type):
    return session.query(CreditTransaction).filter_by(task_id=task_id, type=tx_type).all()


def test_charges_actual_price_and_refunds_unused_hold(db_session):
    """Ядро схемы: холд взят по верхней границе (видео 10 с), списывается ×3 от
    факта (5 с), остаток возвращается — иначе клиент переплачивает вдвое."""
    user, task = _seed_task(db_session, stage=Stage.VIDEO)
    hold = task.cost
    balance_after_hold = user.credit_balance

    complete_task(db_session, task_id=task.id, result=_image_success(duration_seconds=5))
    db_session.refresh(task)
    db_session.refresh(user)

    expected_price = price_sparks(task.real_cost_usd)
    assert task.price == expected_price
    assert expected_price < hold  # иначе тест не проверяет возврат

    charges = _ledger(db_session, task.id, CreditTransactionType.CHARGE)
    assert [c.amount for c in charges] == [expected_price]

    releases = _ledger(db_session, task.id, CreditTransactionType.RELEASE)
    assert [r.amount for r in releases] == [hold - expected_price]
    assert user.credit_balance == balance_after_hold + (hold - expected_price)


def test_longer_scene_costs_the_client_more(db_session):
    """Пропорциональность наценки: вдвое более длинное видео -> вдвое дороже
    для клиента. Фиксированная смета дала бы одинаковую цену и просевшую маржу."""
    _, short_task = _seed_task(db_session, stage=Stage.VIDEO)
    complete_task(db_session, task_id=short_task.id, result=_image_success(duration_seconds=5))

    _, long_task = _seed_task(db_session, stage=Stage.VIDEO)
    complete_task(db_session, task_id=long_task.id, result=_image_success(duration_seconds=10))

    db_session.refresh(short_task)
    db_session.refresh(long_task)
    assert long_task.price == 2 * short_task.price


def test_fixed_cost_stage_has_nothing_to_refund(db_session):
    """У IMAGE себестоимость фиксированная (1 кадр Runway), поэтому верхняя
    граница и факт совпадают — возврата быть не должно."""
    _, task = _seed_task(db_session, stage=Stage.IMAGE)

    complete_task(db_session, task_id=task.id, result=_image_success())
    db_session.refresh(task)

    assert task.price == task.cost
    # Баланс здесь не проверяем: завершение IMAGE двигает DAG дальше и _advance
    # тут же холдирует следующую стадию — движение баланса к списанию не относится.
    assert _ledger(db_session, task.id, CreditTransactionType.RELEASE) == []


def test_missing_usage_charges_full_hold(db_session):
    """Провайдер не вернул usage -> фактической себестоимости нет. Списываем весь
    холд: отдать генерацию бесплатно хуже, чем округлить в свою пользу."""
    user, task = _seed_task(db_session, stage=Stage.VIDEO)
    hold = task.cost
    balance_after_hold = user.credit_balance

    no_usage = ProviderJobResult(
        provider_job_id="job-1",
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": "test/settle-no-usage", "content_type": "image/png"},),
        usage=None,
    )
    complete_task(db_session, task_id=task.id, result=no_usage)
    db_session.refresh(task)
    db_session.refresh(user)

    assert task.real_cost_usd is None
    assert task.price == hold
    assert _ledger(db_session, task.id, CreditTransactionType.RELEASE) == []
    assert user.credit_balance == balance_after_hold


def test_duplicate_completion_settles_only_once(db_session):
    """Гонка poll/webhook не должна ни списать дважды, ни вернуть остаток дважды."""
    user, task = _seed_task(db_session, stage=Stage.VIDEO)
    balance_after_hold = user.credit_balance
    success = _image_success(duration_seconds=5)

    complete_task(db_session, task_id=task.id, result=success)
    db_session.refresh(user)
    balance_after_first = user.credit_balance

    complete_task(db_session, task_id=task.id, result=success)
    db_session.refresh(user)

    assert len(_ledger(db_session, task.id, CreditTransactionType.CHARGE)) == 1
    assert len(_ledger(db_session, task.id, CreditTransactionType.RELEASE)) == 1
    assert user.credit_balance == balance_after_first
    assert user.credit_balance > balance_after_hold
