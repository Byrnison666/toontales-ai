from functools import lru_cache

from toontales_ai.adapters.audio.elevenlabs import ElevenLabsAdapter
from toontales_ai.adapters.base import ProviderAdapter
from toontales_ai.adapters.stubs import ImmediateMediaStubAdapter, LipsyncPassthroughAdapter, StoryboardStubAdapter
from toontales_ai.domain.enums import Stage

_STATIC_ADAPTERS: dict[Stage, ProviderAdapter] = {
    Stage.STORYBOARD: StoryboardStubAdapter(),
    Stage.IMAGE: ImmediateMediaStubAdapter(content_type="image/png"),
    Stage.VIDEO: ImmediateMediaStubAdapter(content_type="video/mp4"),
    Stage.LIPSYNC: LipsyncPassthroughAdapter(),
}


@lru_cache
def _audio_adapter() -> ProviderAdapter:
    # Ленивая инициализация: ElevenLabsAdapter() валидирует наличие api_key/voice_id
    # в конструкторе. Создавать её eagerly на уровне модуля означало бы, что отсутствие
    # ключа в окружении (CI, dev без .env) роняет импорт adapters.registry целиком —
    # для ВСЕХ стадий, а не только audio.
    return ElevenLabsAdapter()


def get_adapter(stage: Stage) -> ProviderAdapter:
    if stage == Stage.AUDIO:
        return _audio_adapter()
    return _STATIC_ADAPTERS[stage]
