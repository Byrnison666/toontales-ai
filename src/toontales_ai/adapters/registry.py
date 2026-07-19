from toontales_ai.adapters.base import ProviderAdapter
from toontales_ai.adapters.stubs import ImmediateMediaStubAdapter, LipsyncPassthroughAdapter, StoryboardStubAdapter
from toontales_ai.domain.enums import Stage

ADAPTER_REGISTRY: dict[Stage, ProviderAdapter] = {
    Stage.STORYBOARD: StoryboardStubAdapter(),
    Stage.IMAGE: ImmediateMediaStubAdapter(content_type="image/png"),
    Stage.VIDEO: ImmediateMediaStubAdapter(content_type="video/mp4"),
    Stage.AUDIO: ImmediateMediaStubAdapter(content_type="audio/mpeg"),
    Stage.LIPSYNC: LipsyncPassthroughAdapter(),
}


def get_adapter(stage: Stage) -> ProviderAdapter:
    return ADAPTER_REGISTRY[stage]
