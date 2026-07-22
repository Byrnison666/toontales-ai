"""Bearer-токен — JWT access-токен (security/auth.py), не user_id напрямую.
Ownership-проверки (review.md §6) полагаются на user_id, извлечённый из
подписанного и верифицированного токена."""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.config.settings import get_settings
from toontales_ai.security.auth import InvalidTokenError, decode_access_token
from toontales_ai.storage.db import AsyncSessionLocal


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user_id(authorization: str = Header(...)) -> uuid.UUID:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expected Bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        return decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")


def require_admin(x_admin_key: str = Header(...)) -> None:
    """Guard для admin-эндпоинтов (billing topup, admin-панель). В MVP нет ролей —
    защита общим секретом X-Admin-Key. Пустой admin_api_key в конфиге НЕ должен
    открывать эндпоинт для любого значения ключа."""
    admin_key = get_settings().admin_api_key
    if not admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
