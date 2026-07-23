import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GenerateProjectRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=200)
    script_text: str = Field(min_length=1, max_length=4000)  # жёсткий лимит входа (review.md §10)


class GenerateProjectResponse(BaseModel):
    project_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    estimated_cost: int
    max_budget: int


class SparkPackageItem(BaseModel):
    sparks: int
    price_rub: int


class SparkPackagesResponse(BaseModel):
    """Прайс пакетов искр. Публичный: оферта обещает показывать стоимость на
    странице оплаты, которая доступна без входа в аккаунт."""

    packages: list[SparkPackageItem]


class PricingQuoteResponse(BaseModel):
    """Верхняя граница резерва на генерацию, в искрах. Фактическое списание
    считается по себестоимости стадий и обычно заметно ниже."""

    max_hold: int


class TaskSnapshot(BaseModel):
    task_id: uuid.UUID
    scene_id: uuid.UUID | None
    stage: str
    status: str
    progress_hint: str
    # Цена в искрах: cost — заблокированный холд, price — фактическое списание
    # (None, пока задача не завершилась). Себестоимость в USD клиенту не отдаётся,
    # она есть только в админской выдаче (api/v1/admin.py).
    cost: int
    price: int | None
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
    # Сколько искр реально списано за run на текущий момент (сумма Task.price).
    total_price: int
    scenes: list[SceneSnapshot]
    tasks: list[TaskSnapshot]
    assets: list[MediaAssetSnapshot]


class PartialRerunRequest(BaseModel):
    stage: str
    scene_id: uuid.UUID | None = None


class WsTicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int
