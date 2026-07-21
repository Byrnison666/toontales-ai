import uuid

import jwt
import pytest

from toontales_ai.config import settings as settings_module
from toontales_ai.security.auth import (
    AuthConfigError,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _configure_jwt_secret(monkeypatch):
    monkeypatch.setenv("TOONTALES_JWT_SECRET", "test-secret-that-is-at-least-32-bytes-long")
    settings_module.get_settings.cache_clear()


def test_hash_password_is_not_plaintext_and_verifies():
    password_hash = hash_password("correct horse battery staple")
    assert password_hash != "correct horse battery staple"
    assert verify_password("correct horse battery staple", password_hash)


def test_verify_password_rejects_wrong_password():
    password_hash = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", password_hash)


def test_verify_password_rejects_malformed_hash():
    assert not verify_password("anything", "not-a-valid-argon2-hash")


def test_create_and_decode_access_token_roundtrip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_decode_access_token_rejects_tampered_signature():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_decode_access_token_rejects_expired_token(monkeypatch):
    monkeypatch.setenv("TOONTALES_JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "-1")
    settings_module.get_settings.cache_clear()
    token = create_access_token(uuid.uuid4())
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_token_signed_with_different_secret():
    token = jwt.encode(
        {"sub": str(uuid.uuid4())}, "a-different-secret-thats-also-32-bytes-plus", algorithm="HS256"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_token_without_subject():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"iat": now, "exp": now + timedelta(minutes=5)},
        "test-secret-that-is-at-least-32-bytes-long",
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_token_missing_exp_claim():
    """require=['exp','iat','sub'] в decode: без него PyJWT не проверяет exp,
    если claim'а вообще нет в токене — токен, подписанный тем же секретом,
    был бы бессрочным (security-ревью)."""
    token = jwt.encode(
        {"sub": str(uuid.uuid4())}, "test-secret-that-is-at-least-32-bytes-long", algorithm="HS256"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_create_access_token_raises_config_error_when_secret_missing(monkeypatch):
    monkeypatch.setenv("TOONTALES_JWT_SECRET", "")
    settings_module.get_settings.cache_clear()
    with pytest.raises(AuthConfigError):
        create_access_token(uuid.uuid4())


def test_create_access_token_raises_config_error_when_secret_too_short(monkeypatch):
    monkeypatch.setenv("TOONTALES_JWT_SECRET", "short-secret")
    settings_module.get_settings.cache_clear()
    with pytest.raises(AuthConfigError):
        create_access_token(uuid.uuid4())
