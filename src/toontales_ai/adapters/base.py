from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from toontales_ai.domain.enums import ProviderJobStatus


@dataclass(frozen=True, slots=True)
class StageInput:
    task_id: str
    scene_id: str | None
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderSubmission:
    """submit() может вернуть job id для последующего polling ИЛИ готовый
    результат немедленно (review.md §2) — оба случая нормализуются одинаково."""

    provider_job_id: str | None
    status: ProviderJobStatus
    result: "ProviderJobResult | None" = None


@dataclass(frozen=True, slots=True)
class ProviderJobResult:
    provider_job_id: str | None
    status: ProviderJobStatus
    artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    error_code: str | None = None
    error_detail: str | None = None
    retry_after_seconds: int | None = None


@runtime_checkable
class ProviderAdapter(Protocol):
    """Базовый контракт. НЕ включает webhook — polling-only провайдеры
    (review.md §10) не обязаны его реализовывать."""

    async def submit(
        self,
        payload: StageInput,
        *,
        idempotency_key: str,
    ) -> ProviderSubmission:
        """Отправляет job провайдеру. Не блокируется в ожидании результата."""
        ...

    async def poll(self, provider_job_id: str) -> ProviderJobResult:
        """Возвращает нормализованный статус без блокирующего ожидания."""
        ...


@runtime_checkable
class WebhookCapableAdapter(Protocol):
    """Отдельная capability-интерфейс для провайдеров с webhook-поддержкой
    (review.md §10: обязательный parse_webhook в базовом Protocol — over-engineering
    для polling-only адаптеров)."""

    async def parse_webhook(
        self,
        *,
        headers: Mapping[str, str],
        raw_body: bytes,
    ) -> ProviderJobResult:
        """Проверяет подпись и timestamp (защита от replay) до разбора тела."""
        ...
