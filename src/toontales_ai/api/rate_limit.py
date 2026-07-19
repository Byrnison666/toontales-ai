"""Rate limiting / backpressure на пользователя (review.md §10, пробел "нет rate
limiting и backpressure"). Fixed-window counter в Redis — минимально достаточно
для MVP; не защищает от глобальной конкурентности по провайдеру (review.md §10
второстепенный пункт "quota/429 по провайдеру") — это отдельная задача уровня
provider adapter, не входит в этот шаг."""

import time
import uuid

import redis
from fastapi import HTTPException, status

from toontales_ai.config.settings import get_settings

_settings = get_settings()
_redis_client = redis.Redis.from_url(
    _settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
)


def check_rate_limit(*, user_id: uuid.UUID, action: str, limit_per_minute: int) -> None:
    window = int(time.time() // 60)
    key = f"toontales:ratelimit:{action}:{user_id}:{window}"

    count = _redis_client.incr(key)
    if count == 1:
        _redis_client.expire(key, 60)

    if count > limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded for '{action}': {limit_per_minute}/min",
        )
