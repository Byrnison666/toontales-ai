"""AnthropicStoryboardAdapter — реальный vendor HTTP API, мокается на уровне
httpx.AsyncClient (CLAUDE.md: моки уместны для внешних/медленных зависимостей).
Живая проверка против настоящего Anthropic API — ручная, вне автоматического
набора (нет ключа для CI)."""

import json

import httpx
import pytest

from toontales_ai.adapters.base import StageInput
from toontales_ai.adapters.storyboard import anthropic as anthropic_module
from toontales_ai.adapters.storyboard.anthropic import (
    AnthropicAPIError,
    AnthropicConfigError,
    AnthropicStoryboardAdapter,
)
from toontales_ai.config import settings as settings_module
from toontales_ai.domain.enums import ProviderJobStatus


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _configure_anthropic(monkeypatch):
    monkeypatch.setenv("TOONTALES_ANTHROPIC_API_KEY", "key-1")
    settings_module.get_settings.cache_clear()


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self) -> dict:
        return self._json_data


class _FakeAsyncClient:
    post_response: _FakeResponse
    last_post_call: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers, json):
        type(self).last_post_call = {"url": url, "headers": headers, "json": json}
        return type(self).post_response


def _messages_response(scenes: list[dict]) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps({"scenes": scenes})}],
        "usage": {"input_tokens": 120, "output_tokens": 340},
    }


def _sample_scene() -> dict:
    return {
        "script_text": "A fox enters the forest.",
        "image_prompt": "a red fox walking into a glowing forest, cinematic",
        "camera_movement": "slow pan left",
        "mood_notes": "mysterious",
    }


def test_config_error_when_api_key_missing(monkeypatch):
    monkeypatch.setenv("TOONTALES_ANTHROPIC_API_KEY", "")
    settings_module.get_settings.cache_clear()

    with pytest.raises(AnthropicConfigError):
        AnthropicStoryboardAdapter()


async def test_submit_sends_expected_body_and_returns_scenes(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    scenes = [_sample_scene(), _sample_scene()]
    _FakeAsyncClient.post_response = _FakeResponse(200, json_data=_messages_response(scenes))

    adapter = AnthropicStoryboardAdapter()
    submission = await adapter.submit(
        StageInput(task_id="t1", scene_id=None, payload={"script_text": "A fox explores a magical forest."}),
        idempotency_key="run1:storyboard_generation:v1",
    )

    assert submission.status == ProviderJobStatus.SUCCEEDED
    assert submission.result is not None
    assert submission.result.artifacts[0]["scenes"] == scenes
    assert submission.result.usage == {"input_tokens": 120, "output_tokens": 340}

    body = _FakeAsyncClient.last_post_call["json"]
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["messages"] == [{"role": "user", "content": "A fox explores a magical forest."}]
    assert body["output_config"]["format"]["type"] == "json_schema"
    # minItems/maxItems > 1 не поддерживаются grammar-constrained decoding у Anthropic
    # (живой 400: "'minItems' values other than 0 or 1 are not supported") — диапазон
    # MIN_SCENES..MAX_SCENES задаётся только текстом в SYSTEM_PROMPT.
    assert "minItems" not in body["output_config"]["format"]["schema"]["properties"]["scenes"]
    assert "maxItems" not in body["output_config"]["format"]["schema"]["properties"]["scenes"]
    assert _FakeAsyncClient.last_post_call["headers"]["x-api-key"] == "key-1"


async def test_submit_rejects_empty_script_text(monkeypatch):
    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(AnthropicAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "   "}),
            idempotency_key="k",
        )


@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_submit_raises_transient_error_for_429_and_5xx(monkeypatch, status_code):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(status_code, text="overloaded")

    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(anthropic_module.AnthropicTransientError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story"}),
            idempotency_key="k",
        )


async def test_submit_raises_plain_api_error_for_4xx(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(400, text="bad request")

    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(AnthropicAPIError) as exc_info:
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story"}),
            idempotency_key="k",
        )
    assert not isinstance(exc_info.value, anthropic_module.AnthropicTransientError)


async def test_submit_rejects_response_without_scenes(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(
        200,
        json_data={
            "content": [{"type": "text", "text": json.dumps({"scenes": []})}],
            "usage": {"input_tokens": 120, "output_tokens": 10},
        },
    )

    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(AnthropicAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story"}),
            idempotency_key="k",
        )


async def test_submit_rejects_too_many_scenes(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    too_many = [_sample_scene() for _ in range(anthropic_module.MAX_SCENES + 1)]
    _FakeAsyncClient.post_response = _FakeResponse(200, json_data=_messages_response(too_many))

    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(AnthropicAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story"}),
            idempotency_key="k",
        )


async def test_submit_rejects_invalid_json_text(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(
        200,
        json_data={
            "content": [{"type": "text", "text": "not json"}],
            "usage": {"input_tokens": 120, "output_tokens": 10},
        },
    )

    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(AnthropicAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story"}),
            idempotency_key="k",
        )


async def test_poll_not_implemented():
    adapter = object.__new__(AnthropicStoryboardAdapter)  # обходим __init__/config validation
    with pytest.raises(NotImplementedError):
        await adapter.poll("irrelevant")
