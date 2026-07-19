"""Требует живой Redis (skip, если недоступен)."""

import uuid

import pytest
from fastapi import HTTPException

from toontales_ai.api.rate_limit import _redis_client, check_rate_limit


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
