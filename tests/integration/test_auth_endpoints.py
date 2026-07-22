"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.
register()/login() принимают AsyncSession (реальный API-контракт), а db_session
fixture синхронная (Base.metadata.create_all/drop_all вокруг теста) — используем
db_session только для жизненного цикла схемы/прямого сидинга, а сами вызовы
эндпоинтов — через отдельную AsyncSessionLocal (та же test-БД, другой драйвер),
тот же паттерн, что test_partial_rerun_join_stages.py."""

import pytest
from fastapi import HTTPException

from toontales_ai.api.deps import get_current_user_id
from toontales_ai.api.v1.auth import LoginRequest, RegisterRequest, login, register
from toontales_ai.domain.models import User
from toontales_ai.security.auth import decode_access_token
from toontales_ai.storage.db import AsyncSessionLocal


async def test_register_creates_user_and_returns_valid_token(db_session):
    async with AsyncSessionLocal() as session:
        response = await register(RegisterRequest(email="alice@example.com", password="correct-horse-battery"), session)

    assert decode_access_token(response.access_token) == response.user_id
    user = db_session.get(User, response.user_id)
    assert user.email == "alice@example.com"
    assert user.password_hash != "correct-horse-battery"  # не plaintext


async def test_register_grants_signup_bonus_with_ledger_entry(db_session, monkeypatch):
    from toontales_ai.config import settings as settings_module
    from toontales_ai.domain.enums import CreditTransactionType
    from toontales_ai.domain.models import CreditTransaction

    monkeypatch.setenv("TOONTALES_SIGNUP_BONUS_CREDITS", "2000")
    settings_module.get_settings.cache_clear()
    async with AsyncSessionLocal() as session:
        response = await register(RegisterRequest(email="bonus@example.com", password="correct-horse-battery"), session)
    settings_module.get_settings.cache_clear()

    user = db_session.get(User, response.user_id)
    assert user.credit_balance == 2000
    # Бонус зафиксирован в ledger (append-only), а не "с неба".
    txs = (
        db_session.query(CreditTransaction)
        .filter_by(user_id=response.user_id, type=CreditTransactionType.TOPUP)
        .all()
    )
    assert len(txs) == 1
    assert txs[0].amount == 2000


async def test_register_rejects_duplicate_email(db_session):
    async with AsyncSessionLocal() as session:
        await register(RegisterRequest(email="bob@example.com", password="correct-horse-battery"), session)

    with pytest.raises(HTTPException) as exc_info:
        async with AsyncSessionLocal() as session:
            await register(RegisterRequest(email="bob@example.com", password="another-password"), session)
    assert exc_info.value.status_code == 409


async def test_login_succeeds_with_correct_credentials(db_session):
    async with AsyncSessionLocal() as session:
        registered = await register(
            RegisterRequest(email="carol@example.com", password="correct-horse-battery"), session
        )

    async with AsyncSessionLocal() as session:
        response = await login(LoginRequest(email="carol@example.com", password="correct-horse-battery"), session)

    assert response.user_id == registered.user_id
    assert decode_access_token(response.access_token) == registered.user_id


async def test_login_rejects_wrong_password(db_session):
    async with AsyncSessionLocal() as session:
        await register(RegisterRequest(email="dave@example.com", password="correct-horse-battery"), session)

    with pytest.raises(HTTPException) as exc_info:
        async with AsyncSessionLocal() as session:
            await login(LoginRequest(email="dave@example.com", password="wrong-password"), session)
    assert exc_info.value.status_code == 401


async def test_login_rejects_unknown_email(db_session):
    with pytest.raises(HTTPException) as exc_info:
        async with AsyncSessionLocal() as session:
            await login(LoginRequest(email="nobody@example.com", password="whatever123"), session)
    assert exc_info.value.status_code == 401


async def test_login_rejects_user_without_password_hash(db_session):
    """Пользователь, заведённый напрямую в БД (до появления auth или сидом для
    тестов) без password_hash, не должен иметь возможность залогиниться —
    отдельная проверка, не общий None.password_hash -> AttributeError."""
    user = User(email="legacy@example.com", password_hash=None, credit_balance=0)
    db_session.add(user)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        async with AsyncSessionLocal() as session:
            await login(LoginRequest(email="legacy@example.com", password="anything123"), session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_id_rejects_non_bearer_header():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization="Basic dXNlcjpwYXNz")
    assert exc_info.value.status_code == 401


async def test_get_current_user_id_rejects_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user_id(authorization="Bearer not-a-real-jwt")
    assert exc_info.value.status_code == 401


async def test_get_current_user_id_accepts_valid_token(db_session):
    async with AsyncSessionLocal() as session:
        response = await register(RegisterRequest(email="erin@example.com", password="correct-horse-battery"), session)

    resolved = await get_current_user_id(authorization=f"Bearer {response.access_token}")

    assert resolved == response.user_id
