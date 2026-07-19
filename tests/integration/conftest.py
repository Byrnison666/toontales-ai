"""Интеграционные тесты требуют живой PostgreSQL (JSONB, ON CONFLICT — postgres-specific,
SQLite не подходит). В этом окружении нет ни PostgreSQL, ни Docker — тесты написаны и
структурно корректны, но НЕ были прогнаны против реальной БД. Установите
TOONTALES_DATABASE_URL на тестовую БД и примените alembic upgrade head перед запуском."""

import pytest
from sqlalchemy import text

from toontales_ai.domain.models import Base
from toontales_ai.storage.db import sync_engine


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
