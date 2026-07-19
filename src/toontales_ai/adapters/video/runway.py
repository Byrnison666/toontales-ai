"""Реальный Runway ML image-to-video адаптер для video_generation (заменяет
ImmediateMediaStubAdapter). Контракт подтверждён напрямую по типам официального
Python SDK (context7 был недоступен из-за исчерпанной квоты в этой сессии, а
REST-документация на сайте не раскрывала enum-значения через WebFetch — SPA):

    github.com/runwayml/sdk-python
    src/runwayml/types/image_to_video_create_params.py (модель "gen4.5":
        promptImage — HTTPS URL, promptText — до 1000 UTF-16 code units,
        ratio — один из фиксированного набора, duration — int 2..10)
    src/runwayml/types/task_retrieve_response.py (discriminated union по
        status: PENDING | THROTTLED | RUNNING | CANCELLED | FAILED | SUCCEEDED)

Используем сырые HTTP-вызовы (httpx), а не сам SDK `runwayml` — он покрывает
огромную поверхность API (avatars, voices, workflows и т.д.), не нужную нам,
и добавление такой тяжёлой зависимости требует отдельного согласования
(CLAUDE.md); для пяти полей одного endpoint'а хватает уже используемого httpx.

POST /v1/image_to_video — асинхронная job, возвращает {"id": ...}; статус и
готовый результат опрашиваются через GET /v1/tasks/{id}. Готовое видео Runway
отдаёт как временную (24-48ч) внешнюю ссылку — poll() при SUCCEEDED скачивает
его и перезаливает в наш S3 (аналогично _run_composition в workers/tasks.py:
"скачать чужое, разместить у себя" — свой storage_key, не чужой TTL-URL)."""

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

DEFAULT_DURATION_SECONDS = 5  # gen4.5: int 2..10; ориентир v2.md "до 5-6 сцен на 30-секундный ролик"
VERTICAL_RATIO = "720:1280"  # 9:16 — v2.md "рендер итогового MP4 9:16"
MAX_PROMPT_TEXT_CHARS = 1000  # ограничение gen4.5 promptText (UTF-16 code units)
MAX_OUTPUT_DOWNLOAD_BYTES = 200 * 1024 * 1024


class RunwayConfigError(Exception):
    pass


class RunwayAPIError(Exception):
    """Permanent (не транзиентная) ошибка: невалидный вход, конфигурация, 4xx
    кроме 429. Ведёт к domain-level FAILED/retry_count в complete_task()."""

    pass


class RunwayTransientError(RunwayAPIError):
    """429 (rate limit) и 5xx — временная перегрузка/сбой на стороне Runway, а не
    ошибка запроса. Добавлен в TRANSIENT_ERRORS (workers/tasks.py) — Celery-level
    autoretry_for отработает быстрый backoff вместо немедленного сжигания
    domain-level retry_count за проблему, которая не связана с содержимым задачи."""

    pass


def _raise_for_status(response: httpx.Response, *, context: str) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise RunwayTransientError(f"{context}: {response.status_code} {response.text[:500]}")
    if response.status_code >= 400:
        raise RunwayAPIError(f"{context}: {response.status_code} {response.text[:500]}")


def _build_prompt_text(payload: dict) -> str:
    parts = [
        str(payload.get("image_prompt") or "").strip(),
        f"Camera movement: {payload['camera_movement']}." if payload.get("camera_movement") else "",
        f"Mood: {payload['mood_notes']}." if payload.get("mood_notes") else "",
    ]
    text = " ".join(p for p in parts if p)
    # Лимит gen4.5 promptText — 1000 UTF-16 code units, не Python code points:
    # astral-символы (emoji и т.п.) кодируются двумя UTF-16 unit'ами и могли бы
    # молча превысить лимит при обрезании по len(str).
    encoded = text.encode("utf-16-le")
    if len(encoded) > MAX_PROMPT_TEXT_CHARS * 2:
        encoded = encoded[: MAX_PROMPT_TEXT_CHARS * 2]
    return encoded.decode("utf-16-le", errors="ignore")


class RunwayAdapter:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.runway_api_key:
            raise RunwayConfigError("TOONTALES_RUNWAY_API_KEY must be set to use RunwayAdapter")
        self._api_key = settings.runway_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Runway-Version": RUNWAY_API_VERSION,
            "Content-Type": "application/json",
        }

    async def submit(self, payload: StageInput, *, idempotency_key: str) -> ProviderSubmission:
        image_url = payload.payload.get("source_image_url")
        if not image_url:
            raise RunwayAPIError(
                "no source_image_url in payload: video_generation requires the scene's completed image asset"
            )
        prompt_text = _build_prompt_text(payload.payload)
        if not prompt_text:
            raise RunwayAPIError("empty motion prompt: nothing to describe for video generation")

        body = {
            "model": "gen4.5",
            "promptImage": image_url,
            "promptText": prompt_text,
            "ratio": VERTICAL_RATIO,
            "duration": DEFAULT_DURATION_SECONDS,
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{RUNWAY_BASE_URL}/image_to_video", headers=self._headers(), json=body)

        _raise_for_status(response, context="Runway image_to_video request failed")

        data = response.json()
        task_id = data.get("id")
        if not task_id:
            raise RunwayAPIError(f"Runway response missing task id: {data}")

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
            # Не мапим на ProviderJobStatus.CANCELED: pipeline_sync.complete_task()
            # сегодня обрабатывает только SUCCEEDED/FAILED явно — CANCELED там
            # не имеет ветки и оставил бы Task зависшим без ошибки. FAILED с
            # понятным error_code — безопасный путь без изменения общей логики.
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
            storage_key = f"runway/{provider_job_id}.mp4"
            size_bytes = await self._download_and_upload_output(output_urls[0], storage_key)
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
        """Потоковое скачивание во временный файл с ограничением по размеру
        (review.md §10: тот же класс проблемы, что и unbounded download перед
        FFmpeg в workers/tasks.py — считаем фактические байты по мере стрима, а
        не полагаемся на Content-Length) и перезаливка в S3 через уже
        существующий upload_from_path — без накопления всего файла в памяти
        (список chunks + b"".join удваивал бы пиковую память при 200 MiB видео)."""
        with tempfile.NamedTemporaryFile(prefix="runway-output-", suffix=".mp4", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
            total = 0
            try:
                async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            raise RunwayTransientError(f"failed to download Runway output: {response.status_code}")
                        if response.status_code >= 400:
                            raise RunwayAPIError(f"failed to download Runway output: {response.status_code}")
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_OUTPUT_DOWNLOAD_BYTES:
                                raise RunwayAPIError(
                                    f"Runway output exceeds {MAX_OUTPUT_DOWNLOAD_BYTES} bytes, aborting download"
                                )
                            tmp_file.write(chunk)
                tmp_file.flush()
                upload_from_path(tmp_path, storage_key, content_type="video/mp4")
                return total
            finally:
                tmp_path.unlink(missing_ok=True)
