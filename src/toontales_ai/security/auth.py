"""Пароли и JWT access-токены (заменяет MVP-заглушку Bearer=UUID в api/deps.py).

Argon2id (argon2-cffi, дефолтные параметры библиотеки — OWASP-рекомендованный
алгоритм для хранения паролей, устойчивее bcrypt к GPU-перебору) вместо passlib:
passlib не поддерживается разработчиком с 2020 года и конфликтует с новыми
версиями bcrypt (известная проблема "no attribute '__about__'").

JWT — только access-токен без refresh (MVP-решение): при истечении срока
действия (24ч, TOONTALES_JWT_ACCESS_TOKEN_EXPIRES_MINUTES) — повторный логин.
Полноценный refresh-flow с revocation — отдельная задача при появлении спроса
на долгоживущие сессии."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash

from toontales_ai.config.settings import get_settings

_hasher = PasswordHasher()

JWT_SUBJECT_CLAIM = "sub"


class InvalidTokenError(Exception):
    """Токен невалиден, истёк или подписан другим секретом — 401, не 500."""

    pass


class AuthConfigError(Exception):
    """TOONTALES_JWT_SECRET не задан или слишком короткий — не транзиентная
    ошибка окружения. Короткий HS256-секрет (RFC 7518 §3.2 рекомендует минимум
    32 байта = 256 бит для HS256) подбирается офлайн по перехваченному токену —
    security-ревью нашло, что PyJWT сам это только предупреждением, не отказом."""

    pass


MIN_JWT_SECRET_BYTES = 32


def _require_jwt_secret(settings) -> str:
    secret = settings.jwt_secret
    if not secret or len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        raise AuthConfigError(
            f"TOONTALES_JWT_SECRET must be set and at least {MIN_JWT_SECRET_BYTES} bytes long"
        )
    return secret


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False
    return True


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    secret = _require_jwt_secret(settings)
    now = datetime.now(timezone.utc)
    payload = {
        JWT_SUBJECT_CLAIM: str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    secret = _require_jwt_secret(settings)
    try:
        # require=[...]: без этого PyJWT проверяет exp только если claim присутствует —
        # токен, подписанный тем же секретом, но вообще без exp, был бы бессрочным
        # (security-ревью). Здесь все три claim'а всегда кладутся в create_access_token,
        # так что это defense-in-depth, а не смена контракта.
        payload = jwt.decode(
            token, secret, algorithms=[settings.jwt_algorithm], options={"require": ["exp", "iat", "sub"]}
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    subject = payload.get(JWT_SUBJECT_CLAIM)
    if not subject:
        raise InvalidTokenError("token missing subject claim")
    try:
        return uuid.UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("token subject is not a valid UUID") from exc
