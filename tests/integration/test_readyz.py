"""Требует live PostgreSQL и, для happy path, live Redis."""

import json

import pytest
import redis.asyncio as redis

from toontales_ai import main as main_module


async def _skip_if_redis_unavailable() -> None:
    try:
        async with redis.Redis.from_url(
            main_module.settings.redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        ) as redis_client:
            await redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis недоступен в этом окружении: {exc}")


async def test_readyz_returns_ready_with_live_dependencies(db_session) -> None:
    await _skip_if_redis_unavailable()

    response = await main_module.readyz()
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


async def test_readyz_returns_503_when_redis_is_unavailable(db_session, monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "redis_url", "redis://localhost:1/0")

    response = await main_module.readyz()
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"] == "ok"
    assert payload["checks"]["redis"] != "ok"
    assert payload["checks"]["redis"]
