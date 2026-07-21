"""Интеграционные тесты изолированы в отдельной PostgreSQL, потому что fixture удаляет
схему после каждого теста. SQLite не подходит из-за JSONB и ON CONFLICT. По умолчанию
используется БД toontales_test; адрес можно переопределить через
TOONTALES_TEST_DATABASE_URL, но он не должен указывать на dev/prod БД."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from toontales_ai.config.settings import get_settings
from toontales_ai.domain.models import Base


def _database_identity(database_url: str) -> tuple[str, str | None, int | None, str | None]:
    url = make_url(database_url)
    port = url.port or (5432 if url.get_backend_name() == "postgresql" else None)
    host = url.host.lower() if url.host else None
    if host in {"127.0.0.1", "::1"}:
        host = "localhost"
    return url.get_backend_name(), host, port, url.database


settings = get_settings()
if _database_identity(settings.test_database_url) == _database_identity(settings.database_url):
    raise pytest.UsageError(
        "TOONTALES_TEST_DATABASE_URL указывает на ту же БД, что и "
        "TOONTALES_DATABASE_URL; integration-тесты остановлены до выполнения DDL"
    )

test_url = make_url(settings.test_database_url)
test_sync_url = test_url.set(drivername="postgresql+psycopg")
test_async_url = test_url.set(drivername="postgresql+asyncpg")
test_sync_engine = create_engine(test_sync_url, pool_pre_ping=True)
TestSyncSessionLocal = sessionmaker(test_sync_engine, expire_on_commit=False, class_=Session)
test_async_engine = create_async_engine(test_async_url, pool_pre_ping=True)
TestAsyncSessionLocal = async_sessionmaker(
    test_async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


def pytest_configure():
    # Некоторые integration-тесты проходят через async-код приложения. Подмена только
    # в pytest-процессе не даёт этим путям подключиться к dev/prod БД.
    from toontales_ai.storage import db as storage_db

    storage_db.AsyncSessionLocal = TestAsyncSessionLocal


@pytest.fixture(autouse=True)
async def _dispose_async_engine():
    """pytest-asyncio (asyncio_mode=auto) даёт каждому async-тесту свой event loop,
    а test_async_engine.pool переиспользует asyncpg-соединение между тестами — второй
    тест ловит 'Future attached to a different loop'. dispose() после каждого
    теста форсирует новое соединение под новый loop."""
    yield
    await test_async_engine.dispose()


@pytest.fixture()
def db_session():
    try:
        with test_sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Тестовая PostgreSQL недоступна в этом окружении: {exc}")

    Base.metadata.create_all(test_sync_engine)
    session = TestSyncSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        Base.metadata.drop_all(test_sync_engine)
