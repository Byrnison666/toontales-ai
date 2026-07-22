"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.
Admin-хендлеры принимают AsyncSession; db_session (sync) для сидинга."""

import uuid

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
