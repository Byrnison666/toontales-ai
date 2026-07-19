from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from toontales_ai.config.settings import get_settings

_settings = get_settings()

# FastAPI: async engine.
async_engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

# Celery workers: отдельный sync engine (psycopg3), а не переиспользование event loop
# между задачами (review.md §7). Простой и предсказуемый паттерн ценой двух путей
# доступа к БД — сознательный выбор ради корректности жизненного цикла сессии в MVP.
_sync_url = _settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
sync_engine = create_engine(_sync_url, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, class_=Session)
