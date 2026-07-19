"""Redis pub/sub — межпроцессный fan-out WS-событий между несколькими API-инстансами
(review.md §10, пробел 'нет fan-out при нескольких API-инстансах'). event_id — монотонный
counter в Redis для дедупликации/упорядочивания на клиенте (review.md §10)."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import redis

from toontales_ai.config.settings import get_settings

_settings = get_settings()
redis_client = redis.Redis.from_url(
    _settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
)


def _channel(run_id: uuid.UUID | str) -> str:
    return f"toontales:run:{run_id}:events"


def publish_event(
    *,
    run_id: uuid.UUID,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    stage: str,
    stage_index: int,
    total_stages: int,
    status: str,
    progress: int,
    message: str,
    artifact_ids: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    event_id = redis_client.incr(f"toontales:run:{run_id}:event_seq")
    event = {
        "event_id": event_id,
        "project_id": str(project_id),
        "run_id": str(run_id),
        "task_id": str(task_id) if task_id else None,
        "stage": stage,
        "stage_index": stage_index,
        "total_stages": total_stages,
        "status": status,
        "progress": progress,
        "message": message,
        "artifact_ids": artifact_ids or [],
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Bounded buffer последних событий для реконнекта без полного REST-снапшота (best-effort).
    redis_client.rpush(f"toontales:run:{run_id}:event_log", json.dumps(event))
    redis_client.ltrim(f"toontales:run:{run_id}:event_log", -200, -1)
    redis_client.expire(f"toontales:run:{run_id}:event_log", 3600)
    redis_client.publish(_channel(run_id), json.dumps(event))
