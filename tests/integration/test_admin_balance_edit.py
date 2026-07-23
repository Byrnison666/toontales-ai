"""Ручная правка баланса админом.

Требует live PostgreSQL (skip, если недоступна) — см. conftest.py."""

import uuid

import pytest
from fastapi import HTTPException

from toontales_ai.api.v1 import admin
from toontales_ai.domain.enums import CreditTransactionType
from toontales_ai.domain.models import CreditTransaction, User
from toontales_ai.storage.db import AsyncSessionLocal


def _seed_user(session, balance: int) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=balance)
    session.add(user)
    session.commit()
    return user.id


def _ledger(session, user_id):
    return (
        session.query(CreditTransaction)
        .filter_by(user_id=user_id, type=CreditTransactionType.ADJUSTMENT)
        .all()
    )


async def _edit(user_id, **kwargs):
    body = admin.AdminBalanceEditRequest(**kwargs)
    async with AsyncSessionLocal() as session:
        return await admin.edit_user_balance(user_id=user_id, body=body, session=session)


async def test_set_writes_delta_to_ledger_not_absolute_value(db_session):
    """Баланс двигаем проводкой на разницу: ledger append-only и обязан сходиться
    с балансом, иначе сверка перестаёт что-либо значить."""
    user_id = _seed_user(db_session, 1000)

    result = await _edit(user_id, mode="set", amount=2500, note="компенсация за сбой", idempotency_key="k1")

    assert result.credit_balance == 2500
    entries = _ledger(db_session, user_id)
    assert [e.amount for e in entries] == [1500]
    assert entries[0].note == "компенсация за сбой"


async def test_delta_can_take_sparks_away(db_session):
    """То, чего не умел topup: списать, а не только начислить."""
    user_id = _seed_user(db_session, 1000)

    result = await _edit(user_id, mode="delta", amount=-400, note="возврат по заявке", idempotency_key="k2")

    assert result.credit_balance == 600
    assert [e.amount for e in _ledger(db_session, user_id)] == [-400]


async def test_balance_never_goes_negative(db_session):
    user_id = _seed_user(db_session, 100)

    with pytest.raises(HTTPException) as exc_info:
        await _edit(user_id, mode="delta", amount=-500, note="ошибка", idempotency_key="k3")
    assert exc_info.value.status_code == 400

    db_session.expire_all()
    assert db_session.get(User, user_id).credit_balance == 100
    assert _ledger(db_session, user_id) == []


async def test_repeat_with_same_key_does_not_apply_twice(db_session):
    """Двойной клик или ретрай сети не должен списать/начислить дважды."""
    user_id = _seed_user(db_session, 1000)

    first = await _edit(user_id, mode="delta", amount=300, note="бонус", idempotency_key="same")
    second = await _edit(user_id, mode="delta", amount=300, note="бонус", idempotency_key="same")

    assert first.credit_balance == second.credit_balance == 1300
    assert len(_ledger(db_session, user_id)) == 1


async def test_note_is_required(db_session):
    """Ручное изменение чужих денег без основания не должно быть возможным."""
    user_id = _seed_user(db_session, 1000)

    with pytest.raises(Exception):
        await _edit(user_id, mode="delta", amount=100, note="   ", idempotency_key="k4")

    db_session.expire_all()
    assert db_session.get(User, user_id).credit_balance == 1000


async def test_set_to_same_value_is_a_noop(db_session):
    user_id = _seed_user(db_session, 777)

    result = await _edit(user_id, mode="set", amount=777, note="сверка", idempotency_key="k5")

    assert result.credit_balance == 777
    assert _ledger(db_session, user_id) == []


async def test_set_below_zero_rejected(db_session):
    user_id = _seed_user(db_session, 500)

    with pytest.raises(HTTPException):
        await _edit(user_id, mode="set", amount=-1, note="ошибка", idempotency_key="k6")


async def test_unknown_user_rejected(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await _edit(uuid.uuid4(), mode="delta", amount=100, note="кому?", idempotency_key="k7")
    assert exc_info.value.status_code == 400
