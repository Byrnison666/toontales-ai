"""Требует живой Redis (skip, если недоступен) — семафор на Lua исполняется
на стороне Redis, мокать его смысла нет."""

import uuid

import pytest

from toontales_ai.orchestration import provider_semaphore
from toontales_ai.orchestration.provider_semaphore import _redis_client, _key


@pytest.fixture()
def redis_available():
    try:
        _redis_client.ping()
    except Exception as exc:
        pytest.skip(f"Redis недоступен в этом окружении: {exc}")


@pytest.fixture()
def clean_provider(redis_available):
    provider = f"test-{uuid.uuid4()}"
    yield provider
    _redis_client.delete(_key(provider))


def test_acquire_up_to_limit_then_rejects(clean_provider):
    provider = clean_provider
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    assert provider_semaphore.acquire_slot(provider=provider, holder=a, limit=1) is True
    # лимит=1 исчерпан — другой holder не проходит
    assert provider_semaphore.acquire_slot(provider=provider, holder=b, limit=1) is False


def test_acquire_is_reentrant_for_same_holder(clean_provider):
    provider = clean_provider
    a = str(uuid.uuid4())

    assert provider_semaphore.acquire_slot(provider=provider, holder=a, limit=1) is True
    # тот же holder (повторный process_task после requeue/domain-retry) —
    # переиспользует свой слот, не считается новым держателем даже при полном лимите
    assert provider_semaphore.acquire_slot(provider=provider, holder=a, limit=1) is True


def test_release_frees_slot_for_others(clean_provider):
    provider = clean_provider
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    provider_semaphore.acquire_slot(provider=provider, holder=a, limit=1)
    assert provider_semaphore.acquire_slot(provider=provider, holder=b, limit=1) is False

    provider_semaphore.release_slot(provider=provider, holder=a)
    assert provider_semaphore.acquire_slot(provider=provider, holder=b, limit=1) is True


def test_release_is_idempotent(clean_provider):
    provider = clean_provider
    a = str(uuid.uuid4())
    # release несуществующего слота — no-op, не бросает
    provider_semaphore.release_slot(provider=provider, holder=a)
    provider_semaphore.release_slot(provider=provider, holder=a)


def test_higher_limit_allows_more_concurrent_holders(clean_provider):
    provider = clean_provider
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    assert provider_semaphore.acquire_slot(provider=provider, holder=a, limit=2) is True
    assert provider_semaphore.acquire_slot(provider=provider, holder=b, limit=2) is True
    # третий сверх лимита=2 — отклонён
    assert provider_semaphore.acquire_slot(provider=provider, holder=c, limit=2) is False


def test_expired_slot_is_reclaimed_on_next_acquire(clean_provider):
    provider = clean_provider
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    # ttl=0 → слот протухает немедленно (deadline == now), следующий acquire
    # вычистит его через ZREMRANGEBYSCORE и впустит нового держателя.
    provider_semaphore.acquire_slot(provider=provider, holder=a, limit=1, ttl_seconds=0)
    assert provider_semaphore.acquire_slot(provider=provider, holder=b, limit=1, ttl_seconds=60) is True


def test_refresh_extends_only_existing_slot(clean_provider):
    provider = clean_provider
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    provider_semaphore.acquire_slot(provider=provider, holder=a, limit=1, ttl_seconds=60)
    # refresh держащего слот — True
    assert provider_semaphore.refresh_slot(provider=provider, holder=a) is True
    # refresh НЕ держащего слот — False (не создаёт слот, иначе refresh протухшего
    # молча превысил бы лимит)
    assert provider_semaphore.refresh_slot(provider=provider, holder=b) is False
