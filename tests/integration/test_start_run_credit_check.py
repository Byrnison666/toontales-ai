"""Прайсинг v3: старт не резервирует баланс, проверяет цену + активные запуски.

Требует live PostgreSQL (skip, если недоступна) — см. conftest.py."""

import uuid

import pytest

from toontales_ai.domain.enums import RunStatus
from toontales_ai.domain.models import GenerationRun, Project, User
from toontales_ai.orchestration.pipeline_async import InsufficientCreditsError, start_run
from toontales_ai.orchestration.pricing import price_from_duration
from toontales_ai.storage.db import AsyncSessionLocal


def _seed_user_and_project(session, *, credit_balance: int):
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=credit_balance)
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()
    session.commit()
    return user, project


async def test_start_run_rejects_when_balance_below_price(db_session):
    price = price_from_duration(30)
    user, project = _seed_user_and_project(db_session, credit_balance=price - 1)

    async with AsyncSessionLocal() as session:
        with pytest.raises(InsufficientCreditsError):
            await start_run(
                session, project_id=project.id, user_id=user.id, script_text="a story", duration_seconds=30
            )


async def test_start_run_does_not_touch_balance(db_session):
    """v3: на старте баланс НЕ трогаем (ни резерва, ни списания) — списание одно,
    на успехе. Здесь проверяем, что после старта баланс тот же."""
    price = price_from_duration(30)
    user, project = _seed_user_and_project(db_session, credit_balance=price)

    async with AsyncSessionLocal() as session:
        run = await start_run(
            session, project_id=project.id, user_id=user.id, script_text="a story", duration_seconds=30
        )
        await session.commit()

    assert run.price == price
    assert run.duration_seconds == 30
    db_session.refresh(user)
    assert user.credit_balance == price  # баланс не тронут


async def test_start_run_rejects_when_active_runs_would_oversubscribe(db_session):
    """Резерва нет, поэтому оверсабскрипшн параллельными роликами ловится проверкой:
    баланс должен покрыть этот ролик + уже активные. Второй старт при балансе ровно
    на один ролик должен отказать."""
    price = price_from_duration(30)
    user, project = _seed_user_and_project(db_session, credit_balance=price)

    async with AsyncSessionLocal() as session:
        first = await start_run(
            session, project_id=project.id, user_id=user.id, script_text="story one", duration_seconds=30
        )
        await session.commit()
    assert first.status == RunStatus.RUNNING

    # первый ролик активен и не оплачен (баланс не тронут) — второй не влезает
    async with AsyncSessionLocal() as session:
        with pytest.raises(InsufficientCreditsError):
            await start_run(
                session, project_id=project.id, user_id=user.id, script_text="story two", duration_seconds=30
            )

    # а если первый завершился (перестал быть активным) — второй проходит
    db_session.query(GenerationRun).filter_by(id=first.id).update({"status": RunStatus.COMPLETED})
    db_session.commit()
    async with AsyncSessionLocal() as session:
        second = await start_run(
            session, project_id=project.id, user_id=user.id, script_text="story two", duration_seconds=30
        )
        await session.commit()
    assert second.status == RunStatus.RUNNING
