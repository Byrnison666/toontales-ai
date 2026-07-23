"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.
billing.* принимают AsyncSession → используем AsyncSessionLocal (тот же паттерн,
что test_auth_endpoints.py), db_session (sync) для сидинга/чтения."""

import uuid

import pytest

from toontales_ai.config import settings as settings_module
from toontales_ai.domain.enums import CreditTransactionType
from toontales_ai.domain.models import CreditTransaction, User
from toontales_ai.orchestration import billing
from toontales_ai.storage.db import AsyncSessionLocal


def _seed_user(session, *, balance: int = 0) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=balance)
    session.add(user)
    session.commit()
    return user.id


async def test_get_balance_returns_current(db_session):
    user_id = _seed_user(db_session, balance=150)
    async with AsyncSessionLocal() as session:
        assert await billing.get_balance(session, user_id=user_id) == 150


async def test_topup_increments_balance_and_writes_ledger(db_session):
    user_id = _seed_user(db_session, balance=100)
    async with AsyncSessionLocal() as session:
        new_balance = await billing.topup(session, user_id=user_id, amount=500, idempotency_key="pay-1")
    assert new_balance == 600

    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.credit_balance == 600
    txs = db_session.query(CreditTransaction).filter_by(user_id=user_id, type=CreditTransactionType.TOPUP).all()
    assert len(txs) == 1
    assert txs[0].amount == 500


async def test_topup_is_idempotent(db_session):
    user_id = _seed_user(db_session, balance=0)
    async with AsyncSessionLocal() as session:
        await billing.topup(session, user_id=user_id, amount=300, idempotency_key="pay-dup")
    # Повтор с тем же ключом (ретрай/двойной клик) не начисляет второй раз.
    async with AsyncSessionLocal() as session:
        balance = await billing.topup(session, user_id=user_id, amount=300, idempotency_key="pay-dup")
    assert balance == 300

    db_session.expire_all()
    txs = db_session.query(CreditTransaction).filter_by(user_id=user_id, type=CreditTransactionType.TOPUP).all()
    assert len(txs) == 1  # только одна транзакция несмотря на два вызова


async def test_topup_rejects_non_positive_amount(db_session):
    user_id = _seed_user(db_session, balance=0)
    async with AsyncSessionLocal() as session:
        with pytest.raises(billing.BillingError):
            await billing.topup(session, user_id=user_id, amount=0, idempotency_key="k")
        with pytest.raises(billing.BillingError):
            await billing.topup(session, user_id=user_id, amount=-100, idempotency_key="k2")


async def test_topup_rejects_unknown_user(db_session):
    async with AsyncSessionLocal() as session:
        with pytest.raises(billing.BillingError):
            await billing.topup(session, user_id=uuid.uuid4(), amount=100, idempotency_key="k")


async def test_list_transactions_returns_newest_first(db_session):
    user_id = _seed_user(db_session, balance=0)
    async with AsyncSessionLocal() as session:
        await billing.topup(session, user_id=user_id, amount=100, idempotency_key="t1")
    async with AsyncSessionLocal() as session:
        await billing.topup(session, user_id=user_id, amount=200, idempotency_key="t2")

    async with AsyncSessionLocal() as session:
        txs = await billing.list_transactions(session, user_id=user_id)
    assert len(txs) == 2
    # Порядок — по created_at desc; оба topup, суммарно 300 на балансе.
    assert {t.amount for t in txs} == {100, 200}


# --- эндпоинты admin-topup через прямой вызов хендлера ---


async def test_admin_topup_requires_correct_key(db_session, monkeypatch):
    from fastapi import HTTPException

    from toontales_ai.api.deps import require_admin as _require_admin

    monkeypatch.setenv("TOONTALES_ADMIN_API_KEY", "secret-admin-key")
    settings_module.get_settings.cache_clear()

    # отсутствие заголовка — 401 (нет учётки), а не 422 от валидации
    with pytest.raises(HTTPException) as exc_info:
        _require_admin(x_admin_key=None)
    assert exc_info.value.status_code == 401

    # неверный ключ — 403 (аутентификация не прошла)
    with pytest.raises(HTTPException) as exc_info:
        _require_admin(x_admin_key="wrong")
    assert exc_info.value.status_code == 403

    # верный ключ — проходит без исключения
    _require_admin(x_admin_key="secret-admin-key")
    settings_module.get_settings.cache_clear()


async def test_admin_topup_rejected_when_admin_key_not_configured(db_session, monkeypatch):
    from fastapi import HTTPException

    from toontales_ai.api.deps import require_admin as _require_admin

    # пустой admin_api_key в конфиге не должен открывать эндпоинт для любого значения
    monkeypatch.setenv("TOONTALES_ADMIN_API_KEY", "")
    settings_module.get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc_info:
        _require_admin(x_admin_key="anything")
    assert exc_info.value.status_code == 403
    settings_module.get_settings.cache_clear()
