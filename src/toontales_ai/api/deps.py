"""MVP-заглушка аутентификации: Bearer-токен = user_id (UUID) напрямую.
НЕ production-ready — реальный JWT/OAuth выбор требует отдельного решения
(CLAUDE.md: тяжёлые зависимости — сначала спросить). Здесь только контракт
'кто вызывает', чтобы ownership-проверки (review.md §6) были реализуемы уже сейчас."""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.storage.db import AsyncSessionLocal


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user_id(authorization: str = Header(...)) -> uuid.UUID:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expected Bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        return uuid.UUID(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
