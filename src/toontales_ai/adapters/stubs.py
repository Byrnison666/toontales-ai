"""Стартовые заглушки адаптеров (MVP placeholder, НЕ реальная интеграция с
FLUX/SDXL/Kling/Runway/Luma/ElevenLabs — для этого нужны актуальные API-доки
через context7 и ключи вендоров, вне текущего шага). Все submit() возвращают
результат немедленно (SUCCEEDED), эмулируя синхронный happy path, чтобы
пайплайн был end-to-end прогоняем без внешних сервисов."""

from toontales_ai.adapters.base import ProviderJobResult, ProviderSubmission, StageInput
from toontales_ai.domain.enums import ProviderJobStatus


class StoryboardStubAdapter:
    """LLM-стадия: возвращает фиктивную раскадровку из 2 сцен, если её нет во входе."""

    async def submit(self, payload: StageInput, *, idempotency_key: str) -> ProviderSubmission:
        script_text = str(payload.payload.get("script_text", ""))
        scenes = [
            {
                "script_text": script_text[:200] or "placeholder scene",
                "image_prompt": "stub image prompt",
                "camera_movement": "static",
                "mood_notes": "neutral",
            }
            for _ in range(2)
        ]
        result = ProviderJobResult(
            provider_job_id=None,
            status=ProviderJobStatus.SUCCEEDED,
            artifacts=({"scenes": scenes},),
        )
        return ProviderSubmission(provider_job_id=None, status=ProviderJobStatus.SUCCEEDED, result=result)

    async def poll(self, provider_job_id: str) -> ProviderJobResult:
        raise NotImplementedError("StoryboardStubAdapter завершает работу синхронно в submit()")


class ImmediateMediaStubAdapter:
    """Общая заглушка для image/video/audio/lipsync: submit() сразу возвращает
    один фиктивный artifact с указанным content_type."""

    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    async def submit(self, payload: StageInput, *, idempotency_key: str) -> ProviderSubmission:
        artifact = {
            "storage_key": f"stub/{idempotency_key}",
            "content_type": self._content_type,
        }
        result = ProviderJobResult(
            provider_job_id=None,
            status=ProviderJobStatus.SUCCEEDED,
            artifacts=(artifact,),
        )
        return ProviderSubmission(provider_job_id=None, status=ProviderJobStatus.SUCCEEDED, result=result)

    async def poll(self, provider_job_id: str) -> ProviderJobResult:
        raise NotImplementedError("ImmediateMediaStubAdapter завершает работу синхронно в submit()")


class LipsyncPassthroughAdapter(ImmediateMediaStubAdapter):
    """MVP: lipsync_enabled=false по умолчанию (v2.md stage 5) — адаптер просто
    возвращает исходное видео без изменений."""

    def __init__(self) -> None:
        super().__init__(content_type="video/mp4")
