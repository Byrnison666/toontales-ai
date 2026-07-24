"""Ручной остаток Anthropic: заданная сумма минус наш расход по storyboard с
момента ввода. Требует live PostgreSQL (см. conftest)."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from toontales_ai.domain.enums import RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import (
    GenerationRun,
    ProviderManualBalance,
    Project,
    Task,
    User,
)
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.orchestration.provider_balances import _anthropic_manual
from toontales_ai.storage.db import AsyncSessionLocal


def _seed_storyboard_cost(session, *, cost: Decimal, finished_at: datetime, run: GenerationRun) -> None:
    key = task_idempotency_key(run_id=run.id, stage=Stage.STORYBOARD, scene_id=None, input_version=str(uuid.uuid4()))
    session.add(
        Task(
            run_id=run.id, stage=Stage.STORYBOARD, provider="llm", status=TaskStatus.COMPLETED,
            input_hash=key, idempotency_key=key, real_cost_usd=cost, finished_at=finished_at,
        )
    )
    session.flush()


async def test_manual_balance_not_set_shows_hint(db_session):
    async with AsyncSessionLocal() as session:
        entry = await _anthropic_manual(session)
    assert entry["provider"] == "anthropic"
    assert entry["manual"] is True
    assert entry["available"] is False
    assert "введи вручную" in entry["note"]


async def test_manual_balance_minus_spend(db_session):
    user = User(email=f"{uuid.uuid4()}@x.io", credit_balance=0)
    db_session.add(user)
    db_session.flush()
    project = Project(user_id=user.id, name="p")
    db_session.add(project)
    db_session.flush()
    run = GenerationRun(project_id=project.id, status=RunStatus.COMPLETED)
    db_session.add(run)
    db_session.flush()

    set_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(
        ProviderManualBalance(provider="anthropic", amount_usd=Decimal("20"), set_at=set_at, note="ручной ввод")
    )
    # расход ПОСЛЕ set_at учитывается, ДО — нет
    _seed_storyboard_cost(db_session, cost=Decimal("0.50"), finished_at=set_at + timedelta(hours=1), run=run)
    _seed_storyboard_cost(db_session, cost=Decimal("0.25"), finished_at=set_at + timedelta(hours=2), run=run)
    _seed_storyboard_cost(db_session, cost=Decimal("9.99"), finished_at=set_at - timedelta(hours=1), run=run)
    db_session.commit()

    async with AsyncSessionLocal() as session:
        entry = await _anthropic_manual(session)

    assert entry["available"] is True
    assert entry["unit"] == "usd"
    # 20 − (0.50 + 0.25) = 19.25 (расход до set_at не в счёт)
    assert entry["balance_usd"] == "19.25"
    assert entry["low"] is False  # > $5 порог


async def test_manual_balance_low_flag(db_session):
    set_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(ProviderManualBalance(provider="anthropic", amount_usd=Decimal("3"), set_at=set_at))
    db_session.commit()
    async with AsyncSessionLocal() as session:
        entry = await _anthropic_manual(session)
    assert entry["available"] is True
    assert entry["low"] is True  # $3 < $5 порог
