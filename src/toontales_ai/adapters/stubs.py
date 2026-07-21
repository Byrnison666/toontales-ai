"""Оставшаяся заглушка адаптера (MVP placeholder для STORYBOARD — реальные
image/video/audio/lipsync-провайдеры уже подключены, см. adapters/image/runway.py,
adapters/video/runway.py, adapters/audio/elevenlabs.py, adapters/lipsync/sync_so.py).
submit() возвращает результат немедленно (SUCCEEDED), эмулируя синхронный happy
path для ещё не подключённой стадии."""

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
