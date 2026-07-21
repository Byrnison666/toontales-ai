"""Реальный ElevenLabs Text-to-Speech адаптер для audio_generation (заменяет
ImmediateMediaStubAdapter). Контракт эндпоинта — docs.elevenlabs.io/api-reference/
text-to-speech/convert (context7 был недоступен из-за исчерпанной квоты в этой
сессии; документация получена прямым WebFetch на официальный сайт):

    POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
    Headers: xi-api-key, Content-Type: application/json
    Body: {"text": ..., "model_id": ...}
    200 -> Content-Type: application/octet-stream, тело — сырые байты аудио
    422 -> JSON HTTPValidationError

Ответ синхронный — эндпоинт не возвращает job id для последующего опроса, поэтому
submit() сразу отдаёт готовый результат (как ImmediateMediaStubAdapter), а poll()
не реализован."""

import httpx

from toontales_ai.adapters.base import ProviderJobResult, ProviderSubmission, StageInput
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import ProviderJobStatus
from toontales_ai.storage.s3 import upload_bytes

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
REQUEST_TIMEOUT_SECONDS = 30.0


class ElevenLabsConfigError(Exception):
    """TOONTALES_ELEVENLABS_API_KEY/VOICE_ID не заданы — не транзиентная, не
    подлежащая retry ошибка конфигурации окружения."""

    pass


class ElevenLabsAPIError(Exception):
    """Не-2xx ответ ElevenLabs (кроме сетевых транспортных ошибок — те httpx.TransportError,
    см. workers/tasks.py TRANSIENT_ERRORS) или пустой входной текст."""

    pass


class ElevenLabsAdapter:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
            raise ElevenLabsConfigError(
                "TOONTALES_ELEVENLABS_API_KEY and TOONTALES_ELEVENLABS_VOICE_ID "
                "must be set to use ElevenLabsAdapter"
            )
        self._api_key = settings.elevenlabs_api_key
        self._voice_id = settings.elevenlabs_voice_id
        self._model_id = settings.elevenlabs_model_id

    async def submit(self, payload: StageInput, *, idempotency_key: str) -> ProviderSubmission:
        text = str(payload.payload.get("script_text", "")).strip()
        if not text:
            raise ElevenLabsAPIError("empty script_text: nothing to synthesize")

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{ELEVENLABS_BASE_URL}/text-to-speech/{self._voice_id}",
                headers={"xi-api-key": self._api_key, "Content-Type": "application/json"},
                json={"text": text, "model_id": self._model_id},
            )

        if response.status_code != 200:
            raise ElevenLabsAPIError(
                f"ElevenLabs TTS request failed: {response.status_code} {response.text[:500]}"
            )

        audio_bytes = response.content
        # idempotency_key уже уникален на (run_id, stage, scene_id, input_version) —
        # безопасный storage_key без дополнительного хеширования на этом уровне.
        storage_key = f"elevenlabs/{idempotency_key}.mp3"
        upload_bytes(audio_bytes, storage_key, content_type="audio/mpeg")

        result = ProviderJobResult(
            provider_job_id=None,
            status=ProviderJobStatus.SUCCEEDED,
            artifacts=(
                {
                    "storage_key": storage_key,
                    "content_type": "audio/mpeg",
                    "size_bytes": len(audio_bytes),
                },
            ),
            usage={"characters": len(text)},
        )
        return ProviderSubmission(provider_job_id=None, status=ProviderJobStatus.SUCCEEDED, result=result)

    async def poll(self, provider_job_id: str) -> ProviderJobResult:
        raise NotImplementedError("ElevenLabsAdapter завершает работу синхронно в submit()")
