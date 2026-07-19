"""Требует живой Redis (skip, если недоступен)."""

import time
import uuid

import pytest
from fastapi import HTTPException

from toontales_ai.api.rate_limit import WINDOW_SECONDS, _redis_client, check_rate_limit


@pytest.fixture()
def redis_available():
    try:
        _redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis недоступен в этом окружении: {exc}")


def test_rate_limit_allows_within_budget(redis_available):
    user_id = uuid.uuid4()
    for _ in range(3):
        check_rate_limit(user_id=user_id, action="test_action_a", limit_per_minute=3)


def test_rate_limit_rejects_over_budget(redis_available):
    user_id = uuid.uuid4()
    for _ in range(2):
        check_rate_limit(user_id=user_id, action="test_action_b", limit_per_minute=2)

    with pytest.raises(HTTPException) as exc_info:
        check_rate_limit(user_id=user_id, action="test_action_b", limit_per_minute=2)
    assert exc_info.value.status_code == 429


def test_rate_limit_is_per_user(redis_available):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    check_rate_limit(user_id=user_a, action="test_action_c", limit_per_minute=1)
    check_rate_limit(user_id=user_b, action="test_action_c", limit_per_minute=1)  # разные пользователи — не конфликтует


def test_rate_limit_does_not_allow_2x_burst_at_window_boundary(redis_available):
    """Регрессия review.md §10 P1: fixed-window позволял limit запросов перед сменой
    минуты и ещё limit сразу после — итого 2×limit почти одновременно. Sliding-window
    log должен по-прежнему отклонять сразу после исчерпания лимита, даже если "старые"
    записи искусственно сдвинуты в прошлое ровно за границу окна (симулирует переход
    через минуту без реального time.sleep(60))."""
    user_id = uuid.uuid4()
    action = "test_action_boundary"
    key = f"toontales:ratelimit:{action}:{user_id}"

    for _ in range(2):
        check_rate_limit(user_id=user_id, action=action, limit_per_minute=2)

    # Лимит исчерпан "только что" — немедленный повтор должен быть отклонён,
    # независимо от того, где проходит граница календарной минуты.
    with pytest.raises(HTTPException) as exc_info:
        check_rate_limit(user_id=user_id, action=action, limit_per_minute=2)
    assert exc_info.value.status_code == 429

    # Сдвигаем обе записи в прошлое за пределы окна — эмулирует реальное течение
    # времени без sleep(WINDOW_SECONDS). После этого лимит должен освободиться:
    # sliding window вычищает по фактическому возрасту записи, а не по номеру
    # календарного окна.
    entries = _redis_client.zrange(key, 0, -1, withscores=True)
    _redis_client.delete(key)
    for member, score in entries:
        _redis_client.zadd(key, {member: score - WINDOW_SECONDS - 1})

    check_rate_limit(user_id=user_id, action=action, limit_per_minute=2)  # не должно бросить
