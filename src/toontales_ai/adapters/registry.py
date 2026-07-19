from functools import lru_cache

from toontales_ai.adapters.audio.elevenlabs import ElevenLabsAdapter
from toontales_ai.adapters.base import ProviderAdapter
from toontales_ai.adapters.stubs import ImmediateMediaStubAdapter, LipsyncPassthroughAdapter, StoryboardStubAdapter
from toontales_ai.adapters.video.runway import RunwayAdapter
from toontales_ai.domain.enums import Stage

_STATIC_ADAPTERS: dict[Stage, ProviderAdapter] = {
    Stage.STORYBOARD: StoryboardStubAdapter(),
    Stage.IMAGE: ImmediateMediaStubAdapter(content_type="image/png"),
    Stage.LIPSYNC: LipsyncPassthroughAdapter(),
}

# Стадии с реальными vendor-адаптерами, требующими конфигурацию (api key и т.п.):
# конструируются лениво (functools.lru_cache), а не eagerly на уровне модуля —
# отсутствие ключа в окружении (CI, dev без .env) иначе роняло бы импорт
# adapters.registry целиком для ВСЕХ стадий, а не только для сконфигурированной.


@lru_cache
def _audio_adapter() -> ProviderAdapter:
    return ElevenLabsAdapter()


@lru_cache
def _video_adapter() -> ProviderAdapter:
    return RunwayAdapter()


def get_adapter(stage: Stage) -> ProviderAdapter:
    if stage == Stage.AUDIO:
        return _audio_adapter()
    if stage == Stage.VIDEO:
        return _video_adapter()
    return _STATIC_ADAPTERS[stage]
