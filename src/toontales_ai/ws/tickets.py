"""Короткоживущий одноразовый WS-ticket (review.md §6: замена Bearer-токена
в query parameter, который запрещён из-за утечки в access logs/telemetry).
Ticket сам по себе в query param допустим: он одноразовый, живёт секунды
и не является учётными данными long-lived сессии."""

import secrets
import uuid

import redis

from toontales_ai.config.settings import get_settings

_settings = get_settings()
redis_client = redis.Redis.from_url(
    _settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
)


def _key(ticket: str) -> str:
    return f"toontales:ws-ticket:{ticket}"


def issue_ticket(*, user_id: uuid.UUID, run_id: uuid.UUID) -> str:
    ticket = secrets.token_urlsafe(32)
    redis_client.set(_key(ticket), f"{user_id}:{run_id}", ex=_settings.ws_ticket_ttl_seconds)
    return ticket


def consume_ticket(ticket: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Атомарное чтение+удаление — одноразовость гарантирована на уровне Redis."""
    value = redis_client.getdel(_key(ticket))
    if value is None:
        return None
    user_id_str, run_id_str = value.split(":")
    return uuid.UUID(user_id_str), uuid.UUID(run_id_str)
