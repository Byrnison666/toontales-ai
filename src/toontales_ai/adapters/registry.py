from functools import lru_cache

from toontales_ai.adapters.audio.elevenlabs import ElevenLabsAdapter
from toontales_ai.adapters.base import ProviderAdapter
from toontales_ai.adapters.image.runway import RunwayImageAdapter
from toontales_ai.adapters.lipsync.sync_so import SyncAdapter
from toontales_ai.adapters.storyboard.anthropic import AnthropicStoryboardAdapter
from toontales_ai.adapters.video.runway import RunwayAdapter
from toontales_ai.domain.enums import Stage

# Стадии с реальными vendor-адаптерами, требующими конфигурацию (api key и т.п.):
# конструируются лениво (functools.lru_cache), а не eagerly на уровне модуля —
# отсутствие ключа в окружении (CI, dev без .env) иначе роняло бы импорт
# adapters.registry целиком для ВСЕХ стадий, а не только для сконфигурированной.


@lru_cache
def _storyboard_adapter() -> ProviderAdapter:
    return AnthropicStoryboardAdapter()


@lru_cache
def _audio_adapter() -> ProviderAdapter:
    return ElevenLabsAdapter()


@lru_cache
def _video_adapter() -> ProviderAdapter:
    return RunwayAdapter()


@lru_cache
def _image_adapter() -> ProviderAdapter:
    return RunwayImageAdapter()


@lru_cache
def _lipsync_adapter() -> ProviderAdapter:
    return SyncAdapter()


def get_adapter(stage: Stage) -> ProviderAdapter:
    if stage == Stage.AUDIO:
        return _audio_adapter()
    if stage == Stage.VIDEO:
        return _video_adapter()
    if stage == Stage.IMAGE:
        return _image_adapter()
    if stage == Stage.LIPSYNC:
        return _lipsync_adapter()
    if stage == Stage.STORYBOARD:
        return _storyboard_adapter()
    raise ValueError(f"no adapter registered for stage {stage!r}")
