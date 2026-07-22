"""Admin API — backend для админ-панели. Всё под require_admin (X-Admin-Key).

Read-only обзор системы: пользователи+балансы, runs+себестоимость, агрегаты
экономики, здоровье (readyz + счётчики задач по статусам). Мутации — только
пополнение баланса (см. billing.admin_topup). SQL здесь простой read-only, без
вынесения в отдельный orchestration-слой."""

import uuid
from decimal import Decimal

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.api.deps import get_db_session, require_admin
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import (
    CreditTransaction,
    GenerationRun,
    MediaAsset,
    MediaKind,
    Project,
    Scene,
    Task,
    User,
)
from toontales_ai.storage import db as storage_db
from toontales_ai.storage.s3 import presigned_get_url

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))


# ---------- users ----------


class AdminUserItem(BaseModel):
    id: uuid.UUID
    email: str
    credit_balance: int
    created_at: str


class AdminUsersResponse(BaseModel):
    users: list[AdminUserItem]
    total: int


@router.get("/users", response_model=AdminUsersResponse)
async def list_users(
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> AdminUsersResponse:
    total = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    rows = (
        await session.execute(
            select(User).order_by(User.created_at.desc()).limit(_clamp_limit(limit)).offset(max(0, offset))
        )
    ).scalars().all()
    return AdminUsersResponse(
        users=[
            AdminUserItem(id=u.id, email=u.email, credit_balance=u.credit_balance, created_at=u.created_at.isoformat())
            for u in rows
        ],
        total=total,
    )


class AdminTransactionItem(BaseModel):
    id: uuid.UUID
    type: str
    amount: int
    run_id: uuid.UUID | None
    created_at: str


@router.get("/users/{user_id}/transactions", response_model=list[AdminTransactionItem])
async def user_transactions(
    user_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[AdminTransactionItem]:
    rows = (
        await session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(_clamp_limit(limit))
            .offset(max(0, offset))
        )
    ).scalars().all()
    return [
        AdminTransactionItem(
            id=t.id, type=t.type.value, amount=t.amount, run_id=t.run_id, created_at=t.created_at.isoformat()
        )
        for t in rows
    ]


# ---------- runs ----------


class AdminRunItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_email: str
    status: str
    trigger: str
    estimated_cost: int
    real_cost_usd: str | None
    created_at: str
    finished_at: str | None


class AdminRunsResponse(BaseModel):
    runs: list[AdminRunItem]
    total: int


@router.get("/runs", response_model=AdminRunsResponse)
async def list_runs(
    status_filter: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> AdminRunsResponse:
    # real_cost_usd рана = сумма Task.real_cost_usd по его задачам (тот же смысл,
    # что total_real_cost_usd в пользовательском GET /runs/{id}).
    cost_subq = (
        select(Task.run_id, func.sum(Task.real_cost_usd).label("real_cost"))
        .group_by(Task.run_id)
        .subquery()
    )
    base = (
        select(GenerationRun, User.email, cost_subq.c.real_cost)
        .join(Project, Project.id == GenerationRun.project_id)
        .join(User, User.id == Project.user_id)
        .outerjoin(cost_subq, cost_subq.c.run_id == GenerationRun.id)
    )
    count_base = select(func.count()).select_from(GenerationRun)
    if status_filter:
        try:
            rs = RunStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unknown run status")
        base = base.where(GenerationRun.status == rs)
        count_base = count_base.where(GenerationRun.status == rs)

    total = (await session.execute(count_base)).scalar_one()
    rows = (
        await session.execute(
            base.order_by(GenerationRun.created_at.desc()).limit(_clamp_limit(limit)).offset(max(0, offset))
        )
    ).all()
    return AdminRunsResponse(
        runs=[
            AdminRunItem(
                id=run.id,
                project_id=run.project_id,
                user_email=email,
                status=run.status.value,
                trigger=run.trigger.value,
                estimated_cost=run.estimated_cost,
                real_cost_usd=str(real_cost) if real_cost is not None else None,
                created_at=run.created_at.isoformat(),
                finished_at=run.finished_at.isoformat() if run.finished_at else None,
            )
            for run, email, real_cost in rows
        ],
        total=total,
    )


class AdminTaskItem(BaseModel):
    id: uuid.UUID
    scene_id: uuid.UUID | None
    stage: str
    status: str
    real_cost_usd: str | None
    error: dict | None


class AdminRunDetail(BaseModel):
    id: uuid.UUID
    user_email: str
    status: str
    total_real_cost_usd: str | None
    tasks: list[AdminTaskItem]
    final_render_url: str | None


@router.get("/runs/{run_id}", response_model=AdminRunDetail)
async def run_detail(run_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> AdminRunDetail:
    row = (
        await session.execute(
            select(GenerationRun, User.email)
            .join(Project, Project.id == GenerationRun.project_id)
            .join(User, User.id == Project.user_id)
            .where(GenerationRun.id == run_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    run, email = row

    tasks = (await session.execute(select(Task).where(Task.run_id == run_id))).scalars().all()
    known_costs = [t.real_cost_usd for t in tasks if t.real_cost_usd is not None]
    total = str(sum(known_costs, Decimal("0"))) if known_costs else None

    final_asset = (
        await session.execute(
            select(MediaAsset).where(MediaAsset.run_id == run_id, MediaAsset.kind == MediaKind.FINAL_RENDER)
        )
    ).scalars().first()
    final_url = presigned_get_url(final_asset.storage_key) if final_asset else None

    return AdminRunDetail(
        id=run.id,
        user_email=email,
        status=run.status.value,
        total_real_cost_usd=total,
        tasks=[
            AdminTaskItem(
                id=t.id,
                scene_id=t.scene_id,
                stage=t.stage.value,
                status=t.status.value,
                real_cost_usd=str(t.real_cost_usd) if t.real_cost_usd is not None else None,
                error=t.error_payload,
            )
            for t in tasks
        ],
        final_render_url=final_url,
    )


# ---------- stats (economics dashboard) ----------


class AdminStatsResponse(BaseModel):
    users_total: int
    runs_total: int
    runs_by_status: dict[str, int]
    completed_runs: int
    total_real_cost_usd: str
    avg_cost_per_completed_run_usd: str | None
    cost_by_stage_usd: dict[str, str]


@router.get("/stats", response_model=AdminStatsResponse)
async def stats(session: AsyncSession = Depends(get_db_session)) -> AdminStatsResponse:
    users_total = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    runs_total = (await session.execute(select(func.count()).select_from(GenerationRun))).scalar_one()

    status_rows = (
        await session.execute(select(GenerationRun.status, func.count()).group_by(GenerationRun.status))
    ).all()
    runs_by_status = {s.value: c for s, c in status_rows}
    completed_runs = runs_by_status.get(RunStatus.COMPLETED.value, 0)

    total_cost = (await session.execute(select(func.coalesce(func.sum(Task.real_cost_usd), 0)))).scalar_one()
    total_cost_dec = Decimal(str(total_cost))

    # Средняя себестоимость завершённого ролика — по сумме стоимости задач
    # COMPLETED-ранов, делённой на число таких ранов.
    completed_cost = (
        await session.execute(
            select(func.coalesce(func.sum(Task.real_cost_usd), 0))
            .join(GenerationRun, GenerationRun.id == Task.run_id)
            .where(GenerationRun.status == RunStatus.COMPLETED)
        )
    ).scalar_one()
    avg_cost = (
        str((Decimal(str(completed_cost)) / completed_runs).quantize(Decimal("0.000001")))
        if completed_runs
        else None
    )

    stage_rows = (
        await session.execute(
            select(Task.stage, func.coalesce(func.sum(Task.real_cost_usd), 0)).group_by(Task.stage)
        )
    ).all()
    cost_by_stage = {stage.value: str(Decimal(str(c))) for stage, c in stage_rows}

    return AdminStatsResponse(
        users_total=users_total,
        runs_total=runs_total,
        runs_by_status=runs_by_status,
        completed_runs=completed_runs,
        total_real_cost_usd=str(total_cost_dec),
        avg_cost_per_completed_run_usd=avg_cost,
        cost_by_stage_usd=cost_by_stage,
    )


# ---------- health ----------


class AdminHealthResponse(BaseModel):
    checks: dict[str, str]
    tasks_by_status: dict[str, int]


@router.get("/health", response_model=AdminHealthResponse)
async def health(session: AsyncSession = Depends(get_db_session)) -> AdminHealthResponse:
    checks: dict[str, str] = {}
    try:
        await session.execute(select(1))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    try:
        async with redis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1.0, socket_timeout=1.0
        ) as r:
            await r.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    status_rows = (await session.execute(select(Task.status, func.count()).group_by(Task.status))).all()
    tasks_by_status = {s.value: c for s, c in status_rows}

    return AdminHealthResponse(checks=checks, tasks_by_status=tasks_by_status)
