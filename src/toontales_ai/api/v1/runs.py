import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.adapters.moderation import ModerationRejectedError
from toontales_ai.api.deps import get_current_user_id, get_db_session
from toontales_ai.api.rate_limit import check_rate_limit
from toontales_ai.api.v1.schemas import (
    DurationPriceItem,
    GenerateProjectRequest,
    GenerateProjectResponse,
    MediaAssetSnapshot,
    PartialRerunRequest,
    PricingQuoteResponse,
    RunSnapshotResponse,
    SparkPackageItem,
    SparkPackagesResponse,
    SceneSnapshot,
    TaskSnapshot,
    WsTicketResponse,
)
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import Stage
from toontales_ai.domain.models import GenerationRun, MediaAsset, Project, Scene, Task
from toontales_ai.orchestration.pipeline_async import (
    InsufficientCreditsError,
    InvalidPartialRerunError,
    request_partial_rerun,
    start_run,
)
from toontales_ai.orchestration.pricing import (
    SPARK_PACKAGE_SIZES,
    package_price_rub,
    price_from_duration,
)

# Пресеты длительности для витрины цен (прайсинг v3). Своя длительность считается
# тем же price_from_duration через query-параметр.
DURATION_PRESETS = (10, 30, 60)
from toontales_ai.storage.s3 import presigned_get_url
from toontales_ai.ws.tickets import issue_ticket

router = APIRouter(prefix="/api/v1")
_settings = get_settings()


async def _load_run_with_ownership(session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID) -> GenerationRun:
    """run.project.user_id == authenticated_user.id (review.md §6) — единая точка
    проверки, используется и REST, и WS."""
    run = (await session.execute(select(GenerationRun).where(GenerationRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    project = (await session.execute(select(Project).where(Project.id == run.project_id))).scalar_one()
    if project.user_id != user_id:
        # 404, не 403 — не подтверждаем существование чужого ресурса.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@router.post("/projects/generate", response_model=GenerateProjectResponse)
async def generate_project(
    body: GenerateProjectRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> GenerateProjectResponse:
    check_rate_limit(user_id=user_id, action="generate", limit_per_minute=_settings.rate_limit_generate_per_minute)

    project = Project(user_id=user_id, name=body.project_name)
    session.add(project)
    await session.flush()

    try:
        run = await start_run(
            session,
            project_id=project.id,
            user_id=user_id,
            script_text=body.script_text,
            duration_seconds=body.duration_seconds,
        )
    except InsufficientCreditsError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    except ModerationRejectedError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return GenerateProjectResponse(
        project_id=project.id,
        run_id=run.id,
        status=run.status.value,
        duration_seconds=run.duration_seconds,
        price=run.price,
    )


@router.get("/pricing/packages", response_model=SparkPackagesResponse)
async def pricing_packages() -> SparkPackagesResponse:
    """Без авторизации: страница оплаты открыта всем, и оферта обязывает
    показывать на ней стоимость пакетов."""
    return SparkPackagesResponse(
        packages=[
            SparkPackageItem(sparks=sparks, price_rub=int(package_price_rub(sparks)))
            for sparks in SPARK_PACKAGE_SIZES
        ]
    )


@router.get("/pricing/quote", response_model=PricingQuoteResponse)
async def pricing_quote(
    duration_seconds: int | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> PricingQuoteResponse:
    """Точная цена по длительностям (прайсинг v3). Всегда возвращает пресеты
    10/30/60; при переданном duration_seconds (своя длительность, 5..90) добавляет
    и его. Это финальная цена — резерва нет, столько и спишется на успехе."""
    durations = list(DURATION_PRESETS)
    if duration_seconds is not None and 5 <= duration_seconds <= 90 and duration_seconds not in durations:
        durations.append(duration_seconds)
    durations.sort()
    return PricingQuoteResponse(
        prices=[DurationPriceItem(duration_seconds=d, price=price_from_duration(d)) for d in durations]
    )


@router.get("/runs/{run_id}", response_model=RunSnapshotResponse)
async def get_run_snapshot(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> RunSnapshotResponse:
    run = await _load_run_with_ownership(session, run_id, user_id)

    scenes = (await session.execute(select(Scene).where(Scene.generation_run_id == run_id).order_by(Scene.scene_index))).scalars().all()
    tasks = (await session.execute(select(Task).where(Task.run_id == run_id))).scalars().all()
    assets = (await session.execute(select(MediaAsset).where(MediaAsset.run_id == run_id))).scalars().all()

    return RunSnapshotResponse(
        run_id=run.id,
        project_id=run.project_id,
        status=run.status.value,
        trigger=run.trigger.value,
        created_at=run.created_at,
        # Прайсинг v3: цена — на уровне run, детерминирована из длительности.
        # Списывается один раз на успехе; здесь показываем финальную цену ролика.
        duration_seconds=run.duration_seconds,
        price=run.price,
        scenes=[SceneSnapshot(scene_id=s.id, scene_index=s.scene_index, script_text=s.script_text) for s in scenes],
        tasks=[
            TaskSnapshot(
                task_id=t.id,
                scene_id=t.scene_id,
                stage=t.stage.value,
                status=t.status.value,
                progress_hint=t.status.value,
                error=t.error_payload,
            )
            for t in tasks
        ],
        assets=[
            MediaAssetSnapshot(
                asset_id=a.id,
                kind=a.kind.value,
                scene_id=a.scene_id,
                presigned_url=presigned_get_url(a.storage_key),
            )
            for a in assets
        ],
    )


@router.post("/runs/{run_id}/partial-rerun", response_model=GenerateProjectResponse)
async def partial_rerun(
    run_id: uuid.UUID,
    body: PartialRerunRequest,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> GenerateProjectResponse:
    check_rate_limit(user_id=user_id, action="partial_rerun", limit_per_minute=_settings.rate_limit_generate_per_minute)
    await _load_run_with_ownership(session, run_id, user_id)

    try:
        stage = Stage(body.stage)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unknown stage")

    try:
        new_run = await request_partial_rerun(
            session, parent_run_id=run_id, stage=stage, scene_id=body.scene_id, user_id=user_id
        )
    except InsufficientCreditsError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc))
    except InvalidPartialRerunError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return GenerateProjectResponse(
        project_id=new_run.project_id,
        run_id=new_run.id,
        status=new_run.status.value,
        duration_seconds=new_run.duration_seconds,
        price=new_run.price,  # 0 — rerun бесплатен
    )


@router.post("/runs/{run_id}/ws-ticket", response_model=WsTicketResponse)
async def create_ws_ticket(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> WsTicketResponse:
    """Короткоживущий одноразовый ticket для WS-подключения (review.md §6):
    заменяет запрещённую передачу Bearer-токена в query parameter."""
    await _load_run_with_ownership(session, run_id, user_id)
    ticket = issue_ticket(user_id=user_id, run_id=run_id)
    return WsTicketResponse(ticket=ticket, expires_in_seconds=_settings.ws_ticket_ttl_seconds)
