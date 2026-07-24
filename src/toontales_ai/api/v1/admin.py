"""Admin API — backend для админ-панели. Всё под require_admin (X-Admin-Key).

Read-only обзор системы: пользователи+балансы, runs+себестоимость, агрегаты
экономики, здоровье (readyz + счётчики задач по статусам). Мутации — только
пополнение баланса (см. billing.admin_topup). SQL здесь простой read-only, без
вынесения в отдельный orchestration-слой."""

import uuid
from typing import Literal
from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.api.deps import get_db_session, require_admin
from toontales_ai.orchestration import billing
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
from toontales_ai.orchestration.pricing import actual_markup, revenue_usd
from toontales_ai.orchestration.real_cost import STAGE_PROVIDER, TARIFF_CHECKED_AT
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


# Потолок на одну ручную операцию — защита от лишнего нуля при вводе.
# ~3000 роликов по текущему прайсингу: любой законной правки хватит с запасом.
MAX_BALANCE_EDIT = 10_000_000


class AdminBalanceEditRequest(BaseModel):
    # set — установить точное значение, delta — начислить (>0) или списать (<0).
    mode: Literal["set", "delta"]
    amount: int = Field(ge=-MAX_BALANCE_EDIT, le=MAX_BALANCE_EDIT)
    # Обязательна: ручное изменение чужих денег без основания не должно быть
    # возможным даже для админа — иначе в ledger нечего предъявить при разборе.
    note: str = Field(min_length=1, max_length=500)
    # Задаёт клиент: повтор при ретрае/двойном клике не применится дважды.
    idempotency_key: str = Field(min_length=1, max_length=200)


class AdminBalanceResponse(BaseModel):
    user_id: uuid.UUID
    credit_balance: int


@router.post("/users/{user_id}/balance", response_model=AdminBalanceResponse)
async def edit_user_balance(
    user_id: uuid.UUID,
    body: AdminBalanceEditRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AdminBalanceResponse:
    if body.mode == "set" and body.amount < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="balance cannot be set below zero")
    try:
        new_balance = await billing.admin_adjust_balance(
            session,
            user_id=user_id,
            mode=body.mode,
            amount=body.amount,
            note=body.note,
            idempotency_key=body.idempotency_key,
        )
    except billing.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return AdminBalanceResponse(user_id=user_id, credit_balance=new_balance)


class AdminTransactionItem(BaseModel):
    id: uuid.UUID
    type: str
    amount: int
    note: str | None
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
            id=t.id,
            type=t.type.value,
            amount=t.amount,
            note=t.note,
            run_id=t.run_id,
            created_at=t.created_at.isoformat(),
        )
        for t in rows
    ]


def _markup_str(sparks: int, cost_usd: Decimal | str | None) -> str | None:
    """Наценка строкой для выдачи. cost_usd приходит из SQL-агрегата, который в
    зависимости от драйвера отдаёт Decimal или строку — приводим явно."""
    if cost_usd is None:
        return None
    markup = actual_markup(sparks, Decimal(str(cost_usd)))
    return str(markup) if markup is not None else None


# ---------- runs ----------


class AdminRunItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_email: str
    status: str
    trigger: str
    # Цена ролика в искрах (прайсинг v3, детерминирована длительностью).
    price: int
    duration_seconds: int
    real_cost_usd: str | None
    # Списано искр с клиента и фактическая наценка (выручка / себестоимость).
    # Расхождение с settings.price_markup означает, что тариф провайдера разошёлся
    # с расчётом в real_cost.py либо стадия завершилась без usage.
    charged_sparks: int
    actual_markup: str | None
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
        select(
            Task.run_id,
            func.sum(Task.real_cost_usd).label("real_cost"),
            func.coalesce(func.sum(Task.price), 0).label("charged"),
        )
        .group_by(Task.run_id)
        .subquery()
    )
    base = (
        select(GenerationRun, User.email, cost_subq.c.real_cost, cost_subq.c.charged)
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
                price=run.price,
                duration_seconds=run.duration_seconds,
                real_cost_usd=str(real_cost) if real_cost is not None else None,
                charged_sparks=charged or 0,
                actual_markup=_markup_str(charged or 0, real_cost),
                created_at=run.created_at.isoformat(),
                finished_at=run.finished_at.isoformat() if run.finished_at else None,
            )
            for run, email, real_cost, charged in rows
        ],
        total=total,
    )


class AdminTaskItem(BaseModel):
    id: uuid.UUID
    scene_id: uuid.UUID | None
    stage: str
    status: str
    real_cost_usd: str | None
    charged_sparks: int | None
    actual_markup: str | None
    error: dict | None


class AdminRunDetail(BaseModel):
    id: uuid.UUID
    user_email: str
    status: str
    total_real_cost_usd: str | None
    total_charged_sparks: int
    actual_markup: str | None
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
    total_cost = sum(known_costs, Decimal("0")) if known_costs else None
    total = str(total_cost) if total_cost is not None else None
    total_charged = sum(t.price for t in tasks if t.price is not None)

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
        total_charged_sparks=total_charged,
        actual_markup=_markup_str(total_charged, total_cost),
        tasks=[
            AdminTaskItem(
                id=t.id,
                scene_id=t.scene_id,
                stage=t.stage.value,
                status=t.status.value,
                real_cost_usd=str(t.real_cost_usd) if t.real_cost_usd is not None else None,
                charged_sparks=t.price,
                actual_markup=_markup_str(t.price, t.real_cost_usd) if t.price is not None else None,
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
    # Выручка (расчётная: списанные искры по цене продажи) и фактическая наценка
    # по всей базе — сверка с settings.price_markup. Расчётная, а не фактическая:
    # искры, начисленные админом через billing.topup, никто не оплачивал.
    total_revenue_usd: str
    total_charged_sparks: int
    actual_markup: str | None


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

    total_charged = (
        await session.execute(select(func.coalesce(func.sum(Task.price), 0)))
    ).scalar_one()

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
        total_revenue_usd=str(revenue_usd(total_charged).quantize(Decimal("0.000001"))),
        total_charged_sparks=total_charged,
        actual_markup=_markup_str(total_charged, total_cost_dec),
    )


# ---------- сверка с инвойсами провайдеров ----------


class ProviderSpendItem(BaseModel):
    provider: str
    estimated_spend_usd: str
    tasks: int
    tariff_checked_at: str | None
    tariff_age_days: int | None


class ProviderSpendResponse(BaseModel):
    """Расчётный расход по провайдерам за период — то, что нужно сверить с их
    инвойсом. Расхождение означает, что тариф в real_cost.py разошёлся с реальным
    прайсом, и наценка на самом деле не та, что показывает дашборд."""

    since: str
    until: str
    providers: list[ProviderSpendItem]


@router.get("/provider-spend", response_model=ProviderSpendResponse)
async def provider_spend(
    since: date_type,
    until: date_type,
    session: AsyncSession = Depends(get_db_session),
) -> ProviderSpendResponse:
    if since > until:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="since must not be after until")

    rows = (
        await session.execute(
            select(Task.stage, func.coalesce(func.sum(Task.real_cost_usd), 0), func.count())
            .where(Task.finished_at >= since, Task.finished_at < until + timedelta(days=1))
            .group_by(Task.stage)
        )
    ).all()

    by_provider: dict[str, tuple[Decimal, int]] = {}
    for stage, spend, count in rows:
        provider = STAGE_PROVIDER[stage]
        prev_spend, prev_count = by_provider.get(provider, (Decimal("0"), 0))
        by_provider[provider] = (prev_spend + Decimal(str(spend)), prev_count + count)

    today = date_type.today()
    return ProviderSpendResponse(
        since=since.isoformat(),
        until=until.isoformat(),
        providers=[
            ProviderSpendItem(
                provider=provider,
                estimated_spend_usd=str(spend.quantize(Decimal("0.000001"))),
                tasks=count,
                tariff_checked_at=(
                    TARIFF_CHECKED_AT[provider].isoformat() if provider in TARIFF_CHECKED_AT else None
                ),
                tariff_age_days=(
                    (today - TARIFF_CHECKED_AT[provider]).days if provider in TARIFF_CHECKED_AT else None
                ),
            )
            for provider, (spend, count) in sorted(by_provider.items())
        ],
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


# ---------- остатки провайдеров ----------


class ProviderBalanceItem(BaseModel):
    provider: str
    label: str
    available: bool
    balance: float | None
    unit: str | None
    balance_usd: str | None
    note: str | None
    reset_at: str | None
    low: bool
    error: str | None
    console_url: str


class ProviderBalancesResponse(BaseModel):
    providers: list[ProviderBalanceItem]


@router.get("/provider-balances", response_model=ProviderBalancesResponse)
async def provider_balances(refresh: bool = False) -> ProviderBalancesResponse:
    """Реальные остатки на счетах провайдеров (когда/какой пополнять). refresh=1
    обходит кеш и дёргает API провайдеров напрямую."""
    from toontales_ai.orchestration.provider_balances import get_provider_balances

    items = await get_provider_balances(force_refresh=refresh)
    return ProviderBalancesResponse(providers=[ProviderBalanceItem(**item) for item in items])
