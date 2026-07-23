"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.
Admin-хендлеры принимают AsyncSession; db_session (sync) для сидинга."""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from toontales_ai.api.v1 import admin
from toontales_ai.domain.enums import RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.storage.db import AsyncSessionLocal


def _seed_run_with_tasks(session) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=1000)
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()
    run = GenerationRun(project_id=project.id, status=RunStatus.COMPLETED)
    session.add(run)
    session.flush()
    for stage, cost in ((Stage.STORYBOARD, "0.003591"), (Stage.VIDEO, "0.500000")):
        key = task_idempotency_key(run_id=run.id, stage=stage, scene_id=None, input_version=str(uuid.uuid4()))
        session.add(
            Task(
                run_id=run.id, stage=stage, provider="x", status=TaskStatus.COMPLETED,
                input_hash=key, idempotency_key=key, cost=10, real_cost_usd=cost,
            )
        )
    session.commit()
    return user.id, run.id


async def test_list_users_returns_seeded_user(db_session):
    user_id, _ = _seed_run_with_tasks(db_session)
    async with AsyncSessionLocal() as session:
        resp = await admin.list_users(session=session)
    assert resp.total >= 1
    assert any(u.id == user_id for u in resp.users)


async def test_list_runs_includes_real_cost(db_session):
    _, run_id = _seed_run_with_tasks(db_session)
    async with AsyncSessionLocal() as session:
        resp = await admin.list_runs(session=session)
    run = next(r for r in resp.runs if r.id == run_id)
    # 0.003591 + 0.500000 = 0.503591
    from decimal import Decimal

    assert Decimal(run.real_cost_usd) == Decimal("0.503591")


async def test_list_runs_status_filter_rejects_unknown(db_session):
    async with AsyncSessionLocal() as session:
        with pytest.raises(HTTPException) as exc_info:
            await admin.list_runs(status_filter="not_a_status", session=session)
    assert exc_info.value.status_code == 400


async def test_run_detail_aggregates_cost_and_tasks(db_session):
    _, run_id = _seed_run_with_tasks(db_session)
    async with AsyncSessionLocal() as session:
        detail = await admin.run_detail(run_id, session=session)
    from decimal import Decimal

    assert Decimal(detail.total_real_cost_usd) == Decimal("0.503591")
    assert {t.stage for t in detail.tasks} == {"storyboard_generation", "video_generation"}


async def test_run_detail_404_for_unknown(db_session):
    async with AsyncSessionLocal() as session:
        with pytest.raises(HTTPException) as exc_info:
            await admin.run_detail(uuid.uuid4(), session=session)
    assert exc_info.value.status_code == 404


async def test_stats_aggregates(db_session):
    _seed_run_with_tasks(db_session)
    async with AsyncSessionLocal() as session:
        s = await admin.stats(session=session)
    from decimal import Decimal

    assert s.runs_total >= 1
    assert s.completed_runs >= 1
    assert Decimal(s.total_real_cost_usd) >= Decimal("0.503591")
    assert "video_generation" in s.cost_by_stage_usd


async def test_health_reports_task_counts(db_session):
    _seed_run_with_tasks(db_session)
    async with AsyncSessionLocal() as session:
        h = await admin.health(session=session)
    assert h.checks["database"] == "ok"
    assert h.tasks_by_status.get("completed", 0) >= 2


async def test_admin_sees_charged_sparks_and_actual_markup(db_session):
    """Админка должна показывать не только себестоимость, но и фактическую наценку —
    иначе расхождение тарифов провайдеров с STAGE_COST_USD_MAX заметно только в логах."""
    _, run_id = _seed_run_with_tasks(db_session)
    # Себестоимость задач 0.503591 -> списание ceil(0.503591 / 0.001) = 504 искры
    # на двоих. Проданы они были за 504 * $0.001 * 3 = $1.512 -> наценка ×3.00.
    from toontales_ai.domain.models import Task as TaskModel

    tasks = db_session.query(TaskModel).filter_by(run_id=run_id).all()
    for task in tasks:
        task.price = 252
    db_session.commit()

    async with AsyncSessionLocal() as session:
        detail = await admin.run_detail(run_id=run_id, session=session)
        listing = await admin.list_runs(session=session)

    assert detail.total_charged_sparks == 504
    assert detail.actual_markup == "3.00"
    assert all(t.charged_sparks == 252 for t in detail.tasks)

    row = next(r for r in listing.runs if r.id == run_id)
    assert row.charged_sparks == 504
    assert row.actual_markup == "3.00"


async def test_markup_is_none_when_cost_price_unknown(db_session):
    """Наценка от нулевой/неизвестной себестоимости — деление на ноль, а не «∞»."""
    from toontales_ai.orchestration.pricing import actual_markup

    assert actual_markup(100, None) is None
    assert actual_markup(100, Decimal("0")) is None


async def test_provider_spend_groups_by_provider_for_invoice_check(db_session):
    """Дрейф тарифов провайдера невидим изнутри: real_cost.py считает по своим
    константам. Единственная сверка — расчёт против инвойса, для неё и эндпоинт."""
    from datetime import date, datetime, timedelta, timezone

    from toontales_ai.domain.models import Task as TaskModel

    _, run_id = _seed_run_with_tasks(db_session)
    now = datetime.now(timezone.utc)
    for task in db_session.query(TaskModel).filter_by(run_id=run_id).all():
        task.finished_at = now
    db_session.commit()

    today = date.today()
    async with AsyncSessionLocal() as session:
        resp = await admin.provider_spend(since=today - timedelta(days=1), until=today, session=session)

    providers = {p.provider: p for p in resp.providers}
    # storyboard -> anthropic ($0.003591), video -> runway ($0.500000)
    assert Decimal(providers["anthropic"].estimated_spend_usd) == Decimal("0.003591")
    assert Decimal(providers["runway"].estimated_spend_usd) == Decimal("0.500000")
    # Возраст тарифа едет вместе с расходом: видно, насколько свежа сверка.
    assert providers["runway"].tariff_age_days is not None
    assert providers["runway"].tariff_checked_at is not None


async def test_provider_spend_rejects_inverted_range(db_session):
    from datetime import date, timedelta

    today = date.today()
    async with AsyncSessionLocal() as session:
        with pytest.raises(HTTPException):
            await admin.provider_spend(since=today, until=today - timedelta(days=1), session=session)
