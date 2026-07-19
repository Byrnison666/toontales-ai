"""Rate limiting / backpressure на пользователя (review.md §10, пробел "нет rate
limiting и backpressure"). Sliding-window log на Redis sorted set — не защищает
от глобальной конкурентности по провайдеру (review.md §10 второстепенный пункт
"quota/429 по провайдеру") — это отдельная задача уровня provider adapter,
не входит в этот шаг."""

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

WINDOW_SECONDS = 60

# Атомарно (сервер Redis выполняет как единую операцию, без гонки между
# ZREMRANGEBYSCORE/ZCARD/ZADD от параллельных запросов): вычищает записи вне окна,
# считает оставшиеся, отклоняет ДО вставки, если лимит уже исчерпан — иначе
# fixed-window счётчик пропускал бы до 2×limit запросов на границе окна
# (review.md §10 P1: "rate limit обходится на границе минуты").
# Время берётся из Redis TIME, а не с часов вызывающего API-инстанса: при clock
# skew между инстансами локальное "now" могло бы либо вычистить ещё актуальные
# записи раньше срока (обход лимита), либо оставить их дольше положенного.
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member_suffix = ARGV[3]

local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    return 0
end
redis.call('ZADD', key, now, tostring(now) .. ':' .. member_suffix)
redis.call('EXPIRE', key, window)
return 1
"""
_sliding_window_allow = _redis_client.register_script(_SLIDING_WINDOW_SCRIPT)


def check_rate_limit(*, user_id: uuid.UUID, action: str, limit_per_minute: int) -> None:
    key = f"toontales:ratelimit:{action}:{user_id}"
    member_suffix = str(uuid.uuid4())

    allowed = _sliding_window_allow(keys=[key], args=[WINDOW_SECONDS, limit_per_minute, member_suffix])
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limit exceeded for '{action}': {limit_per_minute}/min",
        )
