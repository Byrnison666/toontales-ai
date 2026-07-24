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
    last_init_kwargs: dict | None = None

    def __init__(self, *args, **kwargs):
        type(self).last_init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers, json):
        type(self).last_post_call = {"url": url, "headers": headers, "json": json}
        return type(self).post_response


def _messages_response(scenes: list[dict]) -> dict:
    # Прайсинг v3: ключи scene_1..scene_N по числу сцен (динамически).
    payload = {f"scene_{i}": scene for i, scene in enumerate(scenes, start=1)}
    return {
        "content": [{"type": "text", "text": json.dumps(payload)}],
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
    from toontales_ai.orchestration.pricing import scene_count_for_duration

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    # duration=10с -> ровно 2 сцены (scene_count_for_duration).
    expected_n = scene_count_for_duration(10)
    scenes = [_sample_scene() for _ in range(expected_n)]
    _FakeAsyncClient.post_response = _FakeResponse(200, json_data=_messages_response(scenes))

    adapter = AnthropicStoryboardAdapter()
    submission = await adapter.submit(
        StageInput(
            task_id="t1", scene_id=None,
            payload={"script_text": "A fox explores a magical forest.", "duration_seconds": 10},
        ),
        idempotency_key="run1:storyboard_generation:v1",
    )

    assert submission.status == ProviderJobStatus.SUCCEEDED
    assert submission.result is not None
    assert submission.result.artifacts[0]["scenes"] == scenes
    assert submission.result.usage == {"input_tokens": 120, "output_tokens": 340}

    body = _FakeAsyncClient.last_post_call["json"]
    assert body["model"] == "claude-sonnet-5"
    assert body["messages"] == [{"role": "user", "content": "A fox explores a magical forest."}]
    assert body["output_config"]["format"]["type"] == "json_schema"
    # Прайсинг v3: число сцен фиксировано длительностью — ровно N ключей, ВСЕ required
    # (additionalProperties=False не даёт больше, required не даёт меньше).
    schema = body["output_config"]["format"]["schema"]
    expected_keys = [f"scene_{i}" for i in range(1, expected_n + 1)]
    assert list(schema["properties"]) == expected_keys
    assert schema["required"] == expected_keys
    assert schema["additionalProperties"] is False
    assert _FakeAsyncClient.last_post_call["headers"]["x-api-key"] == "key-1"


async def test_proxy_passed_to_client_when_configured(monkeypatch):
    monkeypatch.setenv("TOONTALES_ANTHROPIC_PROXY_URL", "http://proxy.example:3128")
    settings_module.get_settings.cache_clear()
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(200, json_data=_messages_response([_sample_scene(), _sample_scene()]))

    adapter = AnthropicStoryboardAdapter()
    await adapter.submit(
        StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story", "duration_seconds": 10}),
        idempotency_key="k",
    )
    assert _FakeAsyncClient.last_init_kwargs["proxy"] == "http://proxy.example:3128"


async def test_no_proxy_when_unset(monkeypatch):
    # TOONTALES_ANTHROPIC_PROXY_URL не задан -> proxy=None (прямое соединение).
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(200, json_data=_messages_response([_sample_scene(), _sample_scene()]))

    adapter = AnthropicStoryboardAdapter()
    await adapter.submit(
        StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story", "duration_seconds": 10}),
        idempotency_key="k",
    )
    assert _FakeAsyncClient.last_init_kwargs["proxy"] is None


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
            "content": [{"type": "text", "text": json.dumps({})}],
            "usage": {"input_tokens": 120, "output_tokens": 10},
        },
    )

    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(AnthropicAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story"}),
            idempotency_key="k",
        )


async def test_submit_rejects_too_few_scenes(monkeypatch):
    # duration=10 -> ждём 2 сцены; пустой ответ (0) < MIN_SCENES -> ошибка.
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(
        200, json_data={"content": [{"type": "text", "text": json.dumps({})}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    )

    adapter = AnthropicStoryboardAdapter()
    with pytest.raises(AnthropicAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story", "duration_seconds": 10}),
            idempotency_key="k",
        )


async def test_submit_collects_all_scene_keys_in_order(monkeypatch):
    # Схема требует ровно N ключей; порядок ключей в JSON не важен — собираем по scene_N.
    from toontales_ai.orchestration.pricing import scene_count_for_duration

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    n = scene_count_for_duration(10)  # 2 сцены
    first = _sample_scene()
    second = _sample_scene() | {"script_text": "The fox reaches the clearing."}
    # ключи в обратном порядке в JSON
    _FakeAsyncClient.post_response = _FakeResponse(
        200,
        json_data={
            "content": [{"type": "text", "text": json.dumps({"scene_2": second, "scene_1": first})}],
            "usage": {"input_tokens": 120, "output_tokens": 40},
        },
    )
    assert n == 2

    adapter = AnthropicStoryboardAdapter()
    submission = await adapter.submit(
        StageInput(task_id="t1", scene_id=None, payload={"script_text": "a story", "duration_seconds": 10}),
        idempotency_key="k",
    )

    assert submission.result is not None
    assert submission.result.artifacts[0]["scenes"] == [first, second]
