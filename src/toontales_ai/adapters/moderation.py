"""Moderation как контракт, а не декларация (review.md §10, пробел: "Moderation
упомянута декларативно, но нет адаптера/провайдера, статусов, timeout/fail-open
vs fail-closed"). Правила модерации применяются к пользовательскому тексту перед
отправкой провайдеру (v2.md §3: "готовность к добавлению... модерации").

Реализация — offline blocklist-адаптер (реально работает без вендорского API/ключей,
в отличие от FLUX/Kling/ElevenLabs-адаптеров). Замена на вендорский Moderation API
(OpenAI Moderation, AWS Comprehend и т.п.) — отдельное решение с context7-доками,
вне объёма этого шага."""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Protocol

from toontales_ai.config.settings import get_settings

# fail-closed истекает по таймауту так же, как по исключению (review.md §10):
# без этого зависший адаптер вешает запрос с уже flush-нутым Project и открытой
# DB-транзакцией навсегда.
MODERATION_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ModerationResult:
    allowed: bool
    category: str | None = None
    reason: str | None = None


class ModerationTimeoutError(Exception):
    pass


class ModerationAdapter(Protocol):
    async def check_text(self, text: str) -> ModerationResult: ...


# Минимальный офлайн-блоклист для MVP. Реальная политика (NSFW/насилие/hate speech
# по категориям) требует вендорского classifier-а — здесь только заведомо грубый
# набор паттернов как демонстрация контракта fail-closed/fail-open.
_BLOCKED_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bkill\s+yourself\b", re.IGNORECASE),
    re.compile(r"\bchild\s+sexual\b", re.IGNORECASE),
    re.compile(r"\bhow\s+to\s+make\s+a\s+bomb\b", re.IGNORECASE),
)


@dataclass(slots=True)
class BlocklistModerationAdapter:
    blocked_patterns: tuple[re.Pattern, ...] = field(default_factory=lambda: _BLOCKED_PATTERNS)

    async def check_text(self, text: str) -> ModerationResult:
        for pattern in self.blocked_patterns:
            if pattern.search(text):
                return ModerationResult(allowed=False, category="blocklist", reason=f"matched pattern: {pattern.pattern}")
        return ModerationResult(allowed=True)


async def moderate_text_or_raise(adapter: ModerationAdapter, text: str) -> None:
    """fail-closed по умолчанию (review.md §10): если модератор упал/протаймаутил,
    контент отклоняется, а не пропускается молча. TOONTALES_MODERATION_FAIL_OPEN=true
    — явный opt-in в обратную политику для окружений, где недоступность модератора
    не должна блокировать пайплайн."""
    settings = get_settings()
    try:
        result = await asyncio.wait_for(adapter.check_text(text), timeout=MODERATION_TIMEOUT_SECONDS)
    except Exception as exc:
        if settings.moderation_fail_open:
            return
        # Причина недоступности — в логах/exception chain, не в сообщении клиенту:
        # не отдаём наружу детали инфраструктуры модерации.
        raise ModerationRejectedError("content rejected: moderation unavailable") from exc

    if not result.allowed:
        # Клиенту — только факт отклонения, без точного паттерна/причины (иначе
        # 422-detail становится подсказкой для подбора обхода блоклиста).
        # result.reason всё ещё доступен вызывающей стороне для аудит-лога.
        raise ModerationRejectedError("content rejected by moderation policy")


class ModerationRejectedError(Exception):
    pass


def get_moderation_adapter() -> ModerationAdapter:
    return BlocklistModerationAdapter()
