"""Интеграционные тесты требуют живой PostgreSQL (JSONB, ON CONFLICT — postgres-specific,
SQLite не подходит) — skip, если недоступна. Локально: settings.database_url по умолчанию
указывает на postgresql+asyncpg://toontales:toontales@localhost:5432/toontales; создайте
роль/БД и примените alembic upgrade head, либо переопределите TOONTALES_DATABASE_URL."""

import pytest
from sqlalchemy import text

from toontales_ai.domain.models import Base
from toontales_ai.storage.db import sync_engine


@pytest.fixture(autouse=True)
async def _dispose_async_engine():
    """pytest-asyncio (asyncio_mode=auto) даёт каждому async-тесту свой event loop,
    а async_engine.pool переиспользует asyncpg-соединение между тестами — второй
    тест ловит 'Future attached to a different loop'. dispose() после каждого
    теста форсирует новое соединение под новый loop."""
    yield
    from toontales_ai.storage.db import async_engine

    await async_engine.dispose()


@pytest.fixture()
def db_session():
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL недоступен в этом окружении: {exc}")

    Base.metadata.create_all(sync_engine)
    from toontales_ai.storage.db import SyncSessionLocal

    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(sync_engine)
