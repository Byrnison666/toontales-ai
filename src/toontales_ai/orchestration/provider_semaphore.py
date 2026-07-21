"""Distributed admission control для провайдеров с жёстким лимитом concurrency.

Sync.so (lipsync) на текущем тарифе разрешает лишь N одновременных генераций
(concurrency_limit=1 по умолчанию, см. TOONTALES_SYNC_MAX_CONCURRENCY). Раньше
все lipsync-задачи ролика слались разом, ловили 429 concurrency_limit_reached,
Celery ретраил их, а при исчерпании max_retries задача зависала (P0, чинился в
reconcile_stale_tasks). Семафор ниже отсекает запрос ДО обращения к провайдеру:
задача берёт слот, держит его через границы Celery-задач (process_task submit →
WAITING_PROVIDER → серия poll_task) по своему task_id, освобождает при terminal/
retry статусе. Слот не взялся — задача откладывается (requeue с backoff), а не
бьётся в 429.

Реализация: Redis ZSET, member=task_id, score=deadline (unix ts). TTL защищает
от утечки слота при падении воркера между acquire и release — протухшие слоты
вычищаются при каждом acquire (ZREMRANGEBYSCORE). poll_task обновляет deadline
(refresh) пока провайдер работает, иначе слот протух бы посреди долгой генерации
и впустил бы вторую задачу сверх лимита. acquire реентрантен по task_id: повторный
process_task той же задачи (после requeue/domain-retry) переиспользует свой слот,
а не считается новым держателем.

Все операции атомарны (Lua на стороне Redis) и берут время из Redis TIME, а не с
часов воркера — при clock skew между воркерами локальное now рассинхронизировало
бы TTL-вычистку.

Известные остаточные риски (admission-control-ревью, приняты для MVP — все
деградируют к УЖЕ принятому риску повторного платного submit, который в свою
очередь ловится провайдерским 429 → complete_task FAILED → retry, т.е. не
приводят к потере денег/данных, только к возможному лишнему вызову):

1. TTL-eventual превышение лимита: слот refresh'ится только при успешном poll со
   статусом QUEUED/PROCESSING. Если серия poll'ов теряется/падает дольше
   SLOT_TTL_SECONDS, слот протухнет пока job у провайдера ещё активен — следующий
   acquire впустит вторую генерацию сверх лимита. Полное устранение требует
   renew-механизма, не привязанного к poll (отдельный heartbeat) — вне объёма MVP.

2. ABA-гонка при at-least-once доставке Celery: слот идентифицируется holder'ом
   (task_id), а не попыткой. При двойной доставке одного process_task в узком
   окне transient-ветки (commit PENDING → ZREM выполняются не атомарно с DB) одна
   попытка может ZREM'ить слот, который другая попытка того же task_id только что
   переиспользовала реентрантно. Полное устранение требует fence-token (epoch на
   попытку) — непропорционально MVP, где провайдер на лимите=1."""

import redis

from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import Stage

# Стадии, чей провайдер имеет жёсткий лимит concurrency (admission control).
# Сейчас только LIPSYNC (Sync.so); при появлении других — добавить сюда.
# Держим здесь (а не в workers/tasks.py), чтобы reconcile в workers/beat.py мог
# освобождать слот для тех же стадий без дублирования маппинга.
SEMAPHORE_PROVIDER_BY_STAGE: dict[Stage, str] = {Stage.LIPSYNC: "sync"}

_settings = get_settings()
_redis_client = redis.Redis.from_url(
    _settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.0,
    socket_timeout=1.0,
)

# TTL слота: должен покрывать реалистичное время генерации у провайдера между
# refresh'ами. poll_task обновляет deadline при каждом опросе (макс интервал
# опроса ~ MAX_POLL_BACKOFF_SECONDS=60), TTL с запасом = 5 минут: слот переживёт
# паузу между poll'ами, но протухнет за разумное время, если воркер умер.
SLOT_TTL_SECONDS = 300

# ACQUIRE: реентрантно по holder. Чистит протухшие слоты, обновляет deadline если
# holder уже держит слот, иначе занимает если есть место. Возврат 1/0.
_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local holder = ARGV[1]
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local deadline = now + ttl

redis.call('ZREMRANGEBYSCORE', key, '-inf', now)

if redis.call('ZSCORE', key, holder) then
    redis.call('ZADD', key, deadline, holder)
    redis.call('EXPIRE', key, ttl)
    return 1
end

if redis.call('ZCARD', key) < limit then
    redis.call('ZADD', key, deadline, holder)
    redis.call('EXPIRE', key, ttl)
    return 1
end

return 0
"""

# REFRESH: продлить deadline, ТОЛЬКО если holder всё ещё держит слот (не создаёт
# слот заново, если его успели вычистить/освободить — иначе refresh протухшего
# слота молча превысил бы лимит). Возврат 1/0.
_REFRESH_SCRIPT = """
local key = KEYS[1]
local holder = ARGV[1]
local ttl = tonumber(ARGV[2])

if not redis.call('ZSCORE', key, holder) then
    return 0
end

local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZADD', key, now + ttl, holder)
redis.call('EXPIRE', key, ttl)
return 1
"""

_acquire = _redis_client.register_script(_ACQUIRE_SCRIPT)
_refresh = _redis_client.register_script(_REFRESH_SCRIPT)


def _key(provider: str) -> str:
    return f"toontales:provider-slots:{provider}"


def acquire_slot(*, provider: str, holder: str, limit: int, ttl_seconds: int = SLOT_TTL_SECONDS) -> bool:
    """Пытается занять слот для holder (реентрантно). True — слот у нас."""
    return bool(_acquire(keys=[_key(provider)], args=[holder, limit, ttl_seconds]))


def refresh_slot(*, provider: str, holder: str, ttl_seconds: int = SLOT_TTL_SECONDS) -> bool:
    """Продлевает TTL слота holder, если он ещё держится. True — продлён."""
    return bool(_refresh(keys=[_key(provider)], args=[holder, ttl_seconds]))


def release_slot(*, provider: str, holder: str) -> None:
    """Освобождает слот holder (идемпотентно — ZREM отсутствующего это no-op)."""
    _redis_client.zrem(_key(provider), holder)
