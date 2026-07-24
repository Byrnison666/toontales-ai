"""Реальный Runway gen4_image text-to-image адаптер для image_generation (заменяет
ImmediateMediaStubAdapter). Контракт подтверждён напрямую по типам официального
Python SDK — та же ситуация, что и с video/runway.py (SPA-документация на сайте
не раскрывает enum-значения через WebFetch):

    github.com/runwayml/sdk-python
    src/runwayml/types/text_to_image_create_params.py, класс Gen4Image:
        promptText — non-empty string, до 1000 UTF-16 code units,
        ratio — Literal из фиксированного набора (включает "720:1280"),
        referenceImages — опционально, не используется здесь (нет референсов).

Использует тот же job/poll контракт, что RunwayAdapter (video): POST возвращает
{"id": ...}, GET /v1/tasks/{id} — discriminated union по status."""

import tempfile
from pathlib import Path

import httpx

from toontales_ai.adapters.base import ProviderJobResult, ProviderSubmission, StageInput
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import ProviderJobStatus
from toontales_ai.storage.s3 import upload_from_path

RUNWAY_BASE_URL = "https://api.dev.runwayml.com/v1"
RUNWAY_API_VERSION = "2024-11-06"
REQUEST_TIMEOUT_SECONDS = 30.0
DOWNLOAD_TIMEOUT_SECONDS = 60.0

VERTICAL_RATIO = "720:1280"  # 9:16 — v2.md "рендер итогового MP4 9:16", тот же формат, что video_generation
MAX_PROMPT_TEXT_CHARS = 1000  # gen4_image promptText limit (UTF-16 code units)
MAX_OUTPUT_DOWNLOAD_BYTES = 50 * 1024 * 1024


class RunwayImageConfigError(Exception):
    pass


class RunwayImageAPIError(Exception):
    """Permanent (не транзиентная) ошибка: невалидный вход, конфигурация, 4xx
    кроме 429."""

    pass


class RunwayImageTransientError(RunwayImageAPIError):
    """429 (rate limit) и 5xx — временная перегрузка/сбой на стороне Runway, а не
    ошибка запроса. Тот же класс проблемы, что RunwayTransientError у video-адаптера."""

    pass


def _raise_for_status(response: httpx.Response, *, context: str) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise RunwayImageTransientError(f"{context}: {response.status_code} {response.text[:500]}")
    if response.status_code >= 400:
        raise RunwayImageAPIError(f"{context}: {response.status_code} {response.text[:500]}")


def _build_prompt_text(payload: dict) -> str:
    # Стилевая директива идёт ПЕРВОЙ: гарантирует мультяшный/диснеевский стиль на
    # каждом кадре и не срезается при обрезке по лимиту (обрезается хвост —
    # сценоспецифичное описание, а не стиль).
    style = get_settings().image_style_prompt.strip()
    parts = [
        style,
        str(payload.get("image_prompt") or "").strip(),
        f"Mood: {payload['mood_notes']}." if payload.get("mood_notes") else "",
    ]
    text = " ".join(p for p in parts if p)
    # Тот же UTF-16 code unit лимит, что в video/runway.py _build_prompt_text —
    # astral-символы кодируются двумя unit'ами и могли бы молча превысить лимит
    # при обрезании по len(str).
    encoded = text.encode("utf-16-le")
    if len(encoded) > MAX_PROMPT_TEXT_CHARS * 2:
        encoded = encoded[: MAX_PROMPT_TEXT_CHARS * 2]
    return encoded.decode("utf-16-le", errors="ignore")


class RunwayImageAdapter:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.runway_api_key:
            raise RunwayImageConfigError("TOONTALES_RUNWAY_API_KEY must be set to use RunwayImageAdapter")
        self._api_key = settings.runway_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Runway-Version": RUNWAY_API_VERSION,
            "Content-Type": "application/json",
        }

    async def submit(self, payload: StageInput, *, idempotency_key: str) -> ProviderSubmission:
        prompt_text = _build_prompt_text(payload.payload)
        if not prompt_text:
            raise RunwayImageAPIError("empty image prompt: nothing to describe for image generation")

        body = {
            "model": "gen4_image",
            "promptText": prompt_text,
            "ratio": VERTICAL_RATIO,
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{RUNWAY_BASE_URL}/text_to_image", headers=self._headers(), json=body)

        _raise_for_status(response, context="Runway text_to_image request failed")

        data = response.json()
        task_id = data.get("id")
        if not task_id:
            raise RunwayImageAPIError(f"Runway response missing task id: {data}")

        return ProviderSubmission(provider_job_id=task_id, status=ProviderJobStatus.QUEUED, result=None)

    async def poll(self, provider_job_id: str) -> ProviderJobResult:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{RUNWAY_BASE_URL}/tasks/{provider_job_id}", headers=self._headers())

        _raise_for_status(response, context="Runway task poll failed")

        data = response.json()
        status_raw = data.get("status", "")

        if status_raw in ("PENDING", "THROTTLED"):
            return ProviderJobResult(provider_job_id=provider_job_id, status=ProviderJobStatus.QUEUED)
        if status_raw == "RUNNING":
            return ProviderJobResult(provider_job_id=provider_job_id, status=ProviderJobStatus.PROCESSING)
        if status_raw == "CANCELLED":
            # Тот же выбор, что и в video/runway.py: FAILED вместо CANCELED — pipeline_sync.complete_task()
            # не имеет отдельной ветки для CANCELED.
            return ProviderJobResult(
                provider_job_id=provider_job_id,
                status=ProviderJobStatus.FAILED,
                error_code="CANCELLED",
                error_detail="task was cancelled on Runway's side",
            )
        if status_raw == "FAILED":
            return ProviderJobResult(
                provider_job_id=provider_job_id,
                status=ProviderJobStatus.FAILED,
                error_code=data.get("failureCode"),
                error_detail=data.get("failure"),
            )
        if status_raw == "SUCCEEDED":
            output_urls = data.get("output") or []
            if not output_urls:
                return ProviderJobResult(
                    provider_job_id=provider_job_id,
                    status=ProviderJobStatus.FAILED,
                    error_code="NO_OUTPUT",
                    error_detail="Runway reported success with empty output",
                )
            storage_key = f"runway-image/{provider_job_id}.png"
            size_bytes = await self._download_and_upload_output(output_urls[0], storage_key)
            return ProviderJobResult(
                provider_job_id=provider_job_id,
                status=ProviderJobStatus.SUCCEEDED,
                artifacts=(
                    {"storage_key": storage_key, "content_type": "image/png", "size_bytes": size_bytes},
                ),
                usage={"images": 1},
            )

        return ProviderJobResult(provider_job_id=provider_job_id, status=ProviderJobStatus.PROCESSING)

    async def _download_and_upload_output(self, url: str, storage_key: str) -> int:
        """Идентично RunwayAdapter._download_and_upload_output (video) — потоковое
        скачивание с ограничением по размеру и перезаливка в S3, только меньший
        лимит (изображение, не видео)."""
        with tempfile.NamedTemporaryFile(prefix="runway-image-output-", suffix=".png", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            total = 0
            try:
                async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            raise RunwayImageTransientError(
                                f"failed to download Runway image output: {response.status_code}"
                            )
                        if response.status_code >= 400:
                            raise RunwayImageAPIError(f"failed to download Runway image output: {response.status_code}")
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_OUTPUT_DOWNLOAD_BYTES:
                                raise RunwayImageAPIError(
                                    f"Runway image output exceeds {MAX_OUTPUT_DOWNLOAD_BYTES} bytes, aborting download"
                                )
                            tmp_file.write(chunk)
                tmp_file.flush()
                upload_from_path(tmp_path, storage_key, content_type="image/png")
                return total
            finally:
                tmp_path.unlink(missing_ok=True)
