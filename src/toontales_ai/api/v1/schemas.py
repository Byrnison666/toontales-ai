import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GenerateProjectRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    script_text: str = Field(min_length=1, max_length=4000)  # жёсткий лимит входа (review.md §10)
    # Длительность ролика в секундах: задаёт цену (детерминированно) и форму
    # пайплайна (число сцен, длину клипов). Границы — pricing.MIN/MAX_DURATION.
    duration_seconds: int = Field(ge=5, le=90)


class GenerateProjectResponse(BaseModel):
    project_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    # Точная цена ролика в искрах (прайсинг v3): известна до старта, списывается
    # один раз на успехе. Резерва нет.
    duration_seconds: int
    price: int


class SparkPackageItem(BaseModel):
    sparks: int
    price_rub: int


class SparkPackagesResponse(BaseModel):
    """Прайс пакетов искр. Публичный: оферта обещает показывать стоимость на
    странице оплаты, которая доступна без входа в аккаунт."""

    packages: list[SparkPackageItem]


class DurationPriceItem(BaseModel):
    duration_seconds: int
    price: int


class PricingQuoteResponse(BaseModel):
    """Точная цена по длительностям (прайсинг v3). Пресеты 10/30/60 + текущий
    выбор пользователя считаются одним эндпоинтом. Резерва нет — это финальная
    цена, которая спишется на успехе."""

    prices: list[DurationPriceItem]


class TaskSnapshot(BaseModel):
    task_id: uuid.UUID
    scene_id: uuid.UUID | None
    stage: str
    status: str
    progress_hint: str
    # Прайсинг v3: денег на уровне задачи нет — цена на уровне run
    # (RunSnapshotResponse.price). Задача несёт только прогресс.
    error: dict | None


class SceneSnapshot(BaseModel):
    scene_id: uuid.UUID
    scene_index: int
    script_text: str


class MediaAssetSnapshot(BaseModel):
    asset_id: uuid.UUID
    kind: str
    scene_id: uuid.UUID | None
    presigned_url: str


class RunSnapshotResponse(BaseModel):
    """GET /api/v1/runs/{run_id} — обязательный полный снапшот (v2.md §2.4):
    клиент использует его при загрузке страницы и после реконнекта WS."""

    run_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    trigger: str
    created_at: datetime
    # Прайсинг v3: детерминированная цена ролика из выбранной длительности.
    # Списывается один раз на успешной COMPOSITION; до успеха баланс не тронут.
    duration_seconds: int
    price: int
    scenes: list[SceneSnapshot]
    tasks: list[TaskSnapshot]
    assets: list[MediaAssetSnapshot]


class PartialRerunRequest(BaseModel):
    stage: str
    scene_id: uuid.UUID | None = None


class WsTicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int
