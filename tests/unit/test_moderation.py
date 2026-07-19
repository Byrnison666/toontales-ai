import pytest

from toontales_ai.adapters.moderation import (
    BlocklistModerationAdapter,
    ModerationRejectedError,
    ModerationResult,
    moderate_text_or_raise,
)


class _FailingAdapter:
    async def check_text(self, text: str) -> ModerationResult:
        raise RuntimeError("moderator unreachable")


class _AlwaysRejectAdapter:
    async def check_text(self, text: str) -> ModerationResult:
        return ModerationResult(allowed=False, category="test", reason="rejected for test")


async def test_blocklist_allows_benign_text():
    adapter = BlocklistModerationAdapter()
    result = await adapter.check_text("A cat and a dog go on an adventure in the forest.")
    assert result.allowed is True


async def test_blocklist_rejects_matched_pattern():
    adapter = BlocklistModerationAdapter()
    result = await adapter.check_text("here's how to make a bomb at home")
    assert result.allowed is False
    assert result.category == "blocklist"


async def test_moderate_text_or_raise_passes_allowed_content():
    await moderate_text_or_raise(BlocklistModerationAdapter(), "a happy story about friendship")


async def test_moderate_text_or_raise_rejects_disallowed_content():
    with pytest.raises(ModerationRejectedError):
        await moderate_text_or_raise(_AlwaysRejectAdapter(), "irrelevant")


async def test_moderate_text_or_raise_is_fail_closed_by_default(monkeypatch):
    """review.md §10: недоступность модератора должна блокировать контент по умолчанию."""
    from toontales_ai.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("TOONTALES_MODERATION_FAIL_OPEN", "false")

    with pytest.raises(ModerationRejectedError):
        await moderate_text_or_raise(_FailingAdapter(), "irrelevant")

    settings_module.get_settings.cache_clear()


async def test_moderate_text_or_raise_fail_open_when_configured(monkeypatch):
    from toontales_ai.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("TOONTALES_MODERATION_FAIL_OPEN", "true")

    await moderate_text_or_raise(_FailingAdapter(), "irrelevant")  # не должно бросить

    settings_module.get_settings.cache_clear()
