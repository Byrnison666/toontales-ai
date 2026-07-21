"""Реальный Sync.so lipsync-адаптер для LIPSYNC (заменяет LipsyncPassthroughAdapter).
Контракт подтверждён через WebSearch/WebFetch по официальной документации (context7
был недоступен в этой сессии — OAuth не пройден):

    docs.sync.so/api-reference/api-overview
    docs.sync.so/api-reference/api/generate-api/create

    POST https://api.sync.so/v2/generate
    Headers: x-api-key
    Body: {"model": ..., "input": [{"type": "video", "url": ...}, {"type": "audio", "url": ...}]}
    -> {"id": ..., "status": "PENDING", ...}

    GET https://api.sync.so/v2/generate/{id}
    -> {"id": ..., "status": PENDING|PROCESSING|COMPLETED|FAILED|REJECTED, "outputUrl": ...}

Join-стадия: вход — уже готовые VIDEO (Runway) и AUDIO (ElevenLabs) артефакты сцены
(см. workers/tasks._build_stage_input), а не текстовый промпт."""

import tempfile
from pathlib import Path

import httpx

from toontales_ai.adapters.base import ProviderJobResult, ProviderSubmission, StageInput
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import ProviderJobStatus
from toontales_ai.storage.s3 import upload_from_path

SYNC_BASE_URL = "https://api.sync.so/v2"
REQUEST_TIMEOUT_SECONDS = 30.0
DOWNLOAD_TIMEOUT_SECONDS = 60.0

MAX_OUTPUT_DOWNLOAD_BYTES = 200 * 1024 * 1024


class SyncConfigError(Exception):
    pass


class SyncAPIError(Exception):
    """Permanent (не транзиентная) ошибка: невалидный вход, конфигурация, 4xx
    кроме 429."""

    pass


class SyncTransientError(SyncAPIError):
    """429 (rate limit) и 5xx — временная перегрузка/сбой на стороне Sync.so, а не
    ошибка запроса. Добавлена в TRANSIENT_ERRORS (workers/tasks.py) — та же роль,
    что у RunwayTransientError."""

    pass


def _raise_for_status(response: httpx.Response, *, context: str) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise SyncTransientError(f"{context}: {response.status_code} {response.text[:500]}")
    if response.status_code >= 400:
        raise SyncAPIError(f"{context}: {response.status_code} {response.text[:500]}")


class SyncAdapter:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.sync_api_key:
            raise SyncConfigError("TOONTALES_SYNC_API_KEY must be set to use SyncAdapter")
        self._api_key = settings.sync_api_key
        self._model = settings.sync_model

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key, "Content-Type": "application/json"}

    async def submit(self, payload: StageInput, *, idempotency_key: str) -> ProviderSubmission:
        video_url = payload.payload.get("source_video_url")
        audio_url = payload.payload.get("source_audio_url")
        if not video_url:
            raise SyncAPIError("no source_video_url in payload: lipsync requires the scene's completed video asset")
        if not audio_url:
            raise SyncAPIError("no source_audio_url in payload: lipsync requires the scene's completed audio asset")

        body = {
            "model": self._model,
            "input": [
                {"type": "video", "url": video_url},
                {"type": "audio", "url": audio_url},
            ],
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{SYNC_BASE_URL}/generate", headers=self._headers(), json=body)

        _raise_for_status(response, context="Sync.so generate request failed")

        data = response.json()
        job_id = data.get("id")
        if not job_id:
            raise SyncAPIError(f"Sync.so response missing generation id: {data}")

        return ProviderSubmission(provider_job_id=job_id, status=ProviderJobStatus.QUEUED, result=None)

    async def poll(self, provider_job_id: str) -> ProviderJobResult:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{SYNC_BASE_URL}/generate/{provider_job_id}", headers=self._headers())

        _raise_for_status(response, context="Sync.so generation poll failed")

        data = response.json()
        status_raw = data.get("status", "")

        if status_raw == "PENDING":
            return ProviderJobResult(provider_job_id=provider_job_id, status=ProviderJobStatus.QUEUED)
        if status_raw == "PROCESSING":
            return ProviderJobResult(provider_job_id=provider_job_id, status=ProviderJobStatus.PROCESSING)
        if status_raw == "REJECTED":
            return ProviderJobResult(
                provider_job_id=provider_job_id,
                status=ProviderJobStatus.FAILED,
                error_code="REJECTED",
                error_detail=data.get("error") or "generation rejected by Sync.so",
            )
        if status_raw == "FAILED":
            return ProviderJobResult(
                provider_job_id=provider_job_id,
                status=ProviderJobStatus.FAILED,
                error_code=data.get("errorCode"),
                error_detail=data.get("error"),
            )
        if status_raw == "COMPLETED":
            output_url = data.get("outputUrl")
            if not output_url:
                return ProviderJobResult(
                    provider_job_id=provider_job_id,
                    status=ProviderJobStatus.FAILED,
                    error_code="NO_OUTPUT",
                    error_detail="Sync.so reported COMPLETED with empty outputUrl",
                )
            storage_key = f"sync/{provider_job_id}.mp4"
            size_bytes = await self._download_and_upload_output(output_url, storage_key)
            return ProviderJobResult(
                provider_job_id=provider_job_id,
                status=ProviderJobStatus.SUCCEEDED,
                artifacts=(
                    {"storage_key": storage_key, "content_type": "video/mp4", "size_bytes": size_bytes},
                ),
            )

        # Неизвестный статус — консервативно считаем "ещё выполняется", а не падаем:
        # новые промежуточные статусы вендора не должны рушить пайплайн.
        return ProviderJobResult(provider_job_id=provider_job_id, status=ProviderJobStatus.PROCESSING)

    async def _download_and_upload_output(self, url: str, storage_key: str) -> int:
        """Потоковое скачивание с ограничением по размеру и перезаливка в S3 —
        идентично RunwayAdapter._download_and_upload_output (тот же класс проблемы:
        временная внешняя ссылка на готовое видео, не наш storage)."""
        with tempfile.NamedTemporaryFile(prefix="sync-output-", suffix=".mp4", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            total = 0
            try:
                async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            raise SyncTransientError(f"failed to download Sync.so output: {response.status_code}")
                        if response.status_code >= 400:
                            raise SyncAPIError(f"failed to download Sync.so output: {response.status_code}")
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_OUTPUT_DOWNLOAD_BYTES:
                                raise SyncAPIError(
                                    f"Sync.so output exceeds {MAX_OUTPUT_DOWNLOAD_BYTES} bytes, aborting download"
                                )
                            tmp_file.write(chunk)
                tmp_file.flush()
                upload_from_path(tmp_path, storage_key, content_type="video/mp4")
                return total
            finally:
                tmp_path.unlink(missing_ok=True)
