"""ElevenLabsAdapter — реальный vendor HTTP API, поэтому мокается на уровне httpx.AsyncClient
(CLAUDE.md: моки уместны для внешних/медленных зависимостей). Живой сетевой прогон против
настоящего ElevenLabs — ручная проверка вне автоматического набора, не требует ключа для CI."""

import httpx
import pytest

from toontales_ai.adapters.audio.elevenlabs import ElevenLabsAdapter, ElevenLabsAPIError, ElevenLabsConfigError
from toontales_ai.adapters.base import StageInput
from toontales_ai.config import settings as settings_module


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", text: str = ""):
        self.status_code = status_code
        self.content = content
        self.text = text


class _FakeAsyncClient:
    next_response: _FakeResponse
    last_call: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers, json):
        type(self).last_call = {"url": url, "headers": headers, "json": json}
        return type(self).next_response


def test_config_error_when_api_key_missing(monkeypatch):
    monkeypatch.setenv("TOONTALES_ELEVENLABS_API_KEY", "")
    monkeypatch.setenv("TOONTALES_ELEVENLABS_VOICE_ID", "voice-1")
    settings_module.get_settings.cache_clear()

    with pytest.raises(ElevenLabsConfigError):
        ElevenLabsAdapter()


def test_config_error_when_voice_id_missing(monkeypatch):
    monkeypatch.setenv("TOONTALES_ELEVENLABS_API_KEY", "key-1")
    monkeypatch.setenv("TOONTALES_ELEVENLABS_VOICE_ID", "")
    settings_module.get_settings.cache_clear()

    with pytest.raises(ElevenLabsConfigError):
        ElevenLabsAdapter()


async def test_submit_uploads_audio_and_returns_succeeded(monkeypatch):
    monkeypatch.setenv("TOONTALES_ELEVENLABS_API_KEY", "key-1")
    monkeypatch.setenv("TOONTALES_ELEVENLABS_VOICE_ID", "voice-1")
    settings_module.get_settings.cache_clear()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.next_response = _FakeResponse(200, content=b"fake-mp3-bytes")

    uploaded: dict = {}

    def _fake_upload_bytes(data: bytes, storage_key: str, *, content_type: str) -> None:
        uploaded["data"] = data
        uploaded["storage_key"] = storage_key
        uploaded["content_type"] = content_type

    monkeypatch.setattr("toontales_ai.adapters.audio.elevenlabs.upload_bytes", _fake_upload_bytes)

    adapter = ElevenLabsAdapter()
    submission = await adapter.submit(
        StageInput(task_id="t1", scene_id=None, payload={"script_text": "hello world"}),
        idempotency_key="run1:audio_generation:scene1:v1",
    )

    assert submission.result is not None
    assert submission.result.artifacts[0]["storage_key"] == "elevenlabs/run1:audio_generation:scene1:v1.mp3"
    assert uploaded["data"] == b"fake-mp3-bytes"
    assert uploaded["content_type"] == "audio/mpeg"
    assert _FakeAsyncClient.last_call["headers"]["xi-api-key"] == "key-1"
    assert _FakeAsyncClient.last_call["json"]["text"] == "hello world"


async def test_submit_rejects_empty_script_text(monkeypatch):
    monkeypatch.setenv("TOONTALES_ELEVENLABS_API_KEY", "key-1")
    monkeypatch.setenv("TOONTALES_ELEVENLABS_VOICE_ID", "voice-1")
    settings_module.get_settings.cache_clear()

    adapter = ElevenLabsAdapter()
    with pytest.raises(ElevenLabsAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "   "}),
            idempotency_key="k",
        )


async def test_submit_raises_on_non_200_response(monkeypatch):
    monkeypatch.setenv("TOONTALES_ELEVENLABS_API_KEY", "key-1")
    monkeypatch.setenv("TOONTALES_ELEVENLABS_VOICE_ID", "voice-1")
    settings_module.get_settings.cache_clear()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.next_response = _FakeResponse(422, text='{"detail": "bad request"}')

    adapter = ElevenLabsAdapter()
    with pytest.raises(ElevenLabsAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id=None, payload={"script_text": "hello"}),
            idempotency_key="k",
        )


async def test_poll_not_implemented():
    import pytest as _pytest

    adapter = object.__new__(ElevenLabsAdapter)  # обходим __init__/config validation
    with _pytest.raises(NotImplementedError):
        await adapter.poll("irrelevant")
