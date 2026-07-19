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


class TaskSnapshot(BaseModel):
    task_id: uuid.UUID
    scene_id: uuid.UUID | None
    stage: str
    status: str
    progress_hint: str
    cost: int
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
    scenes: list[SceneSnapshot]
    tasks: list[TaskSnapshot]
    assets: list[MediaAssetSnapshot]


class PartialRerunRequest(BaseModel):
    stage: str
    scene_id: uuid.UUID | None = None


class WsTicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int
