"""Реальные остатки на счетах провайдеров — для админ-панели: сколько ещё можно
потратить и когда/какой счёт пополнять. В отличие от provider_spend (расчётный
расход по нашим захардкоженным тарифам), здесь БАЛАНСЫ, запрошенные у API самих
провайдеров.

Доступность:
  - Runway: GET /v1/organization -> creditBalance (кредиты). Есть, работает из РФ.
  - ElevenLabs: GET /v1/user/subscription -> character_limit - character_count.
    Требует у API-ключа право user_read (иначе 401 — показываем подсказку).
  - Anthropic: публичного API остатка prepaid-баланса нет — только консоль.

Результат кешируется в Redis (TTL), чтобы не дёргать провайдеров на каждый заход
в админку и не упираться в их rate limits. force_refresh обходит кеш (кнопка
«Обновить»)."""

import asyncio
import json
import logging

import httpx
import redis.asyncio as aioredis

from toontales_ai.config.settings import get_settings
from toontales_ai.orchestration.real_cost import (
    ELEVENLABS_USD_PER_CHARACTER,
    RUNWAY_USD_PER_CREDIT,
    RUNWAY_VIDEO_CREDITS_PER_SECOND,
)

logger = logging.getLogger(__name__)

_CACHE_KEY = "toontales:admin:provider_balances"
_HTTP_TIMEOUT = 10.0

RUNWAY_ORG_URL = "https://api.dev.runwayml.com/v1/organization"
RUNWAY_API_VERSION = "2024-11-06"
ELEVENLABS_SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"

# Плотность озвучки (симв/с) — та же, что в pricing.AUDIO_CHARS_PER_SECOND; здесь
# только для оценки «на сколько секунд озвучки хватит остатка символов».
_AUDIO_CHARS_PER_SECOND = 15


def _usd(value) -> str:
    from decimal import Decimal

    return str((Decimal(str(value))).quantize(Decimal("0.01")))


async def _runway() -> dict:
    settings = get_settings()
    entry = {
        "provider": "runway",
        "label": "Runway — картинки и видео",
        "available": False,
        "balance": None,
        "unit": "credits",
        "balance_usd": None,
        "note": None,
        "reset_at": None,
        "low": False,
        "error": None,
        "console_url": "https://dev.runwayml.com/",
    }
    if not settings.runway_api_key:
        entry["error"] = "TOONTALES_RUNWAY_API_KEY не задан"
        return entry
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                RUNWAY_ORG_URL,
                headers={
                    "Authorization": f"Bearer {settings.runway_api_key}",
                    "X-Runway-Version": RUNWAY_API_VERSION,
                },
            )
        if resp.status_code != 200:
            entry["error"] = f"HTTP {resp.status_code}: {resp.text[:150]}"
            return entry
        credits = resp.json().get("creditBalance")
        if credits is None:
            entry["error"] = "ответ без creditBalance"
            return entry
        entry["available"] = True
        entry["balance"] = credits
        entry["balance_usd"] = _usd(credits * float(RUNWAY_USD_PER_CREDIT))
        # На сколько секунд видео хватит (видео — главный драйвер расхода Runway).
        seconds = int(credits / float(RUNWAY_VIDEO_CREDITS_PER_SECOND))
        entry["note"] = f"≈ {seconds} с видео"
        entry["low"] = credits < settings.runway_low_credits_threshold
    except Exception as exc:  # сеть/парсинг — не роняем всю сводку из-за одного провайдера
        logger.warning("runway balance fetch failed", extra={"error": str(exc)})
        entry["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
    return entry


async def _elevenlabs() -> dict:
    settings = get_settings()
    entry = {
        "provider": "elevenlabs",
        "label": "ElevenLabs — озвучка",
        "available": False,
        "balance": None,
        "unit": "characters",
        "balance_usd": None,
        "note": None,
        "reset_at": None,
        "low": False,
        "error": None,
        "console_url": "https://elevenlabs.io/app/subscription",
    }
    if not settings.elevenlabs_api_key:
        entry["error"] = "TOONTALES_ELEVENLABS_API_KEY не задан"
        return entry
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                ELEVENLABS_SUBSCRIPTION_URL, headers={"xi-api-key": settings.elevenlabs_api_key}
            )
        if resp.status_code == 401:
            entry["error"] = "ключу нужно право user_read (добавь в настройках ключа ElevenLabs)"
            return entry
        if resp.status_code != 200:
            entry["error"] = f"HTTP {resp.status_code}: {resp.text[:150]}"
            return entry
        data = resp.json()
        limit = data.get("character_limit")
        used = data.get("character_count")
        if limit is None or used is None:
            entry["error"] = "ответ без character_limit/character_count"
            return entry
        remaining = max(0, limit - used)
        entry["available"] = True
        entry["balance"] = remaining
        entry["balance_usd"] = _usd(remaining * float(ELEVENLABS_USD_PER_CHARACTER))
        seconds = int(remaining / _AUDIO_CHARS_PER_SECOND)
        entry["note"] = f"≈ {seconds} с озвучки"
        entry["low"] = remaining < settings.elevenlabs_low_chars_threshold
        reset_unix = data.get("next_character_count_reset_unix")
        if reset_unix:
            from datetime import datetime, timezone

            entry["reset_at"] = datetime.fromtimestamp(reset_unix, tz=timezone.utc).isoformat()
    except Exception as exc:
        logger.warning("elevenlabs balance fetch failed", extra={"error": str(exc)})
        entry["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
    return entry


async def _anthropic_manual(session) -> dict:
    # У Anthropic нет публичного API остатка prepaid-баланса. Поэтому админ вводит
    # остаток вручную (в USD) на момент set_at, а актуальный остаток = введённая
    # сумма минус наш расход по storyboard (Anthropic Haiku) с этого момента.
    from decimal import Decimal

    from sqlalchemy import func, select

    from toontales_ai.domain.enums import Stage
    from toontales_ai.domain.models import ProviderManualBalance, Task

    settings = get_settings()
    entry = {
        "provider": "anthropic",
        "label": "Anthropic — сценарий (раскадровка)",
        "available": False,
        "balance": None,
        "unit": "usd",
        "balance_usd": None,
        "note": None,
        "reset_at": None,
        "low": False,
        "error": None,
        "console_url": "https://console.anthropic.com/settings/billing",
        "manual": True,  # фронт покажет кнопку «Задать остаток»
    }
    row = await session.get(ProviderManualBalance, "anthropic")
    if row is None:
        entry["note"] = "остаток не задан — введи вручную (кнопка «Задать остаток»)"
        return entry

    spend = (
        await session.execute(
            select(func.coalesce(func.sum(Task.real_cost_usd), 0)).where(
                Task.stage == Stage.STORYBOARD, Task.finished_at >= row.set_at
            )
        )
    ).scalar_one()
    remaining = Decimal(row.amount_usd) - Decimal(str(spend))
    entry["available"] = True
    entry["balance"] = float(remaining)
    entry["balance_usd"] = _usd(remaining)
    entry["set_at"] = row.set_at.isoformat()
    entry["note"] = (
        f"задано ${_usd(row.amount_usd)} от {row.set_at.date().isoformat()}, "
        f"потрачено ${_usd(spend)} с тех пор"
    )
    entry["low"] = remaining < Decimal(str(settings.anthropic_low_usd_threshold))
    return entry


async def get_provider_balances(session, *, force_refresh: bool = False) -> list[dict]:
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        if not force_refresh:
            cached = await client.get(_CACHE_KEY)
            if cached:
                return json.loads(cached)

        runway, elevenlabs, anthropic = await asyncio.gather(
            _runway(), _elevenlabs(), _anthropic_manual(session)
        )
        balances = [runway, elevenlabs, anthropic]

        await client.set(_CACHE_KEY, json.dumps(balances), ex=settings.provider_balance_cache_seconds)
        return balances
    finally:
        await client.aclose()


async def invalidate_cache() -> None:
    """Сбросить кеш сводки — после ручной правки остатка, чтобы показать сразу."""
    settings = get_settings()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.delete(_CACHE_KEY)
    finally:
        await client.aclose()
