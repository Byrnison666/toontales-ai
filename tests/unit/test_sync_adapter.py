"""SyncAdapter — реальный vendor HTTP API (Sync.so lipsync), мокается на уровне
httpx.AsyncClient (CLAUDE.md: моки уместны для внешних/медленных зависимостей).
Живая проверка против настоящего Sync.so API — ручная, вне автоматического набора
(нет ключа для CI)."""

from pathlib import Path

import httpx
import pytest

from toontales_ai.adapters.base import StageInput
from toontales_ai.adapters.lipsync import sync_so as sync_module
from toontales_ai.adapters.lipsync.sync_so import SyncAdapter, SyncAPIError, SyncConfigError
from toontales_ai.config import settings as settings_module
from toontales_ai.domain.enums import ProviderJobStatus


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _configure_sync(monkeypatch):
    monkeypatch.setenv("TOONTALES_SYNC_API_KEY", "key-1")
    settings_module.get_settings.cache_clear()


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self) -> dict:
        return self._json_data


class _FakeStreamResponse:
    def __init__(self, status_code: int, chunks: list[bytes]):
        self.status_code = status_code
        self._chunks = chunks

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncClient:
    post_response: _FakeResponse
    get_response: _FakeResponse
    stream_response: _FakeStreamResponse
    last_post_call: dict | None = None
    last_get_url: str | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers, json):
        type(self).last_post_call = {"url": url, "headers": headers, "json": json}
        return type(self).post_response

    async def get(self, url, *, headers):
        type(self).last_get_url = url
        return type(self).get_response

    def stream(self, method, url):
        return type(self).stream_response


def test_config_error_when_api_key_missing(monkeypatch):
    monkeypatch.setenv("TOONTALES_SYNC_API_KEY", "")
    settings_module.get_settings.cache_clear()

    with pytest.raises(SyncConfigError):
        SyncAdapter()


async def test_submit_sends_expected_body_and_returns_queued(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(200, json_data={"id": "gen_123", "status": "PENDING"})

    adapter = SyncAdapter()
    submission = await adapter.submit(
        StageInput(
            task_id="t1",
            scene_id="s1",
            payload={
                "source_video_url": "https://example.com/scene.mp4",
                "source_audio_url": "https://example.com/scene.mp3",
            },
        ),
        idempotency_key="run1:lipsync:s1:v1",
    )

    assert submission.provider_job_id == "gen_123"
    assert submission.status == ProviderJobStatus.QUEUED
    assert submission.result is None

    body = _FakeAsyncClient.last_post_call["json"]
    assert body["model"] == "lipsync-2"
    assert {"type": "video", "url": "https://example.com/scene.mp4"} in body["input"]
    assert {"type": "audio", "url": "https://example.com/scene.mp3"} in body["input"]
    assert _FakeAsyncClient.last_post_call["headers"]["x-api-key"] == "key-1"


async def test_submit_rejects_missing_video(monkeypatch):
    adapter = SyncAdapter()
    with pytest.raises(SyncAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id="s1", payload={"source_audio_url": "https://example.com/a.mp3"}),
            idempotency_key="k",
        )


async def test_submit_rejects_missing_audio(monkeypatch):
    adapter = SyncAdapter()
    with pytest.raises(SyncAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id="s1", payload={"source_video_url": "https://example.com/v.mp4"}),
            idempotency_key="k",
        )


@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_submit_raises_transient_error_for_429_and_5xx(monkeypatch, status_code):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(status_code, text="overloaded")

    adapter = SyncAdapter()
    with pytest.raises(sync_module.SyncTransientError):
        await adapter.submit(
            StageInput(
                task_id="t1", scene_id="s1",
                payload={"source_video_url": "https://example.com/v.mp4", "source_audio_url": "https://example.com/a.mp3"},
            ),
            idempotency_key="k",
        )


async def test_submit_raises_plain_api_error_for_4xx(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(400, text="bad request")

    adapter = SyncAdapter()
    with pytest.raises(SyncAPIError) as exc_info:
        await adapter.submit(
            StageInput(
                task_id="t1", scene_id="s1",
                payload={"source_video_url": "https://example.com/v.mp4", "source_audio_url": "https://example.com/a.mp3"},
            ),
            idempotency_key="k",
        )
    assert not isinstance(exc_info.value, sync_module.SyncTransientError)


@pytest.mark.parametrize(
    "sync_status,expected",
    [
        ("PENDING", ProviderJobStatus.QUEUED),
        ("PROCESSING", ProviderJobStatus.PROCESSING),
        ("SOME_FUTURE_STATUS", ProviderJobStatus.PROCESSING),
    ],
)
async def test_poll_maps_non_terminal_statuses(monkeypatch, sync_status, expected):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(200, json_data={"id": "gen_123", "status": sync_status})

    adapter = SyncAdapter()
    result = await adapter.poll("gen_123")

    assert result.status == expected


async def test_poll_maps_rejected_to_failed(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(
        200, json_data={"id": "gen_123", "status": "REJECTED", "error": "no face detected"}
    )

    adapter = SyncAdapter()
    result = await adapter.poll("gen_123")

    assert result.status == ProviderJobStatus.FAILED
    assert result.error_code == "REJECTED"
    assert result.error_detail == "no face detected"


async def test_poll_maps_failed_with_error_reason(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(
        200, json_data={"id": "gen_123", "status": "FAILED", "error": "bad video", "errorCode": "INVALID_INPUT"}
    )

    adapter = SyncAdapter()
    result = await adapter.poll("gen_123")

    assert result.status == ProviderJobStatus.FAILED
    assert result.error_code == "INVALID_INPUT"
    assert result.error_detail == "bad video"


async def test_poll_completed_downloads_and_uploads_output(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(
        200,
        json_data={
            "id": "gen_123",
            "status": "COMPLETED",
            "outputUrl": "https://cdn.sync.so/out.mp4",
            "outputDuration": 5.25,
        },
    )
    _FakeAsyncClient.stream_response = _FakeStreamResponse(200, chunks=[b"fake", b"-mp4-", b"bytes"])

    uploaded: dict = {}

    def _fake_upload_from_path(source_path, storage_key: str, *, content_type: str) -> None:
        uploaded["data"] = Path(source_path).read_bytes()
        uploaded["storage_key"] = storage_key
        uploaded["content_type"] = content_type

    monkeypatch.setattr(sync_module, "upload_from_path", _fake_upload_from_path)

    adapter = SyncAdapter()
    result = await adapter.poll("gen_123")

    assert result.status == ProviderJobStatus.SUCCEEDED
    assert result.artifacts[0]["storage_key"] == "sync/gen_123.mp4"
    assert result.artifacts[0]["size_bytes"] == len(b"fake-mp4-bytes")
    assert result.usage == {"duration_seconds": 5.25}
    assert uploaded["data"] == b"fake-mp4-bytes"
    assert uploaded["content_type"] == "video/mp4"


async def test_poll_completed_with_empty_output_is_failed(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(200, json_data={"id": "gen_123", "status": "COMPLETED"})

    adapter = SyncAdapter()
    result = await adapter.poll("gen_123")

    assert result.status == ProviderJobStatus.FAILED
    assert result.error_code == "NO_OUTPUT"


async def test_download_output_enforces_size_limit(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(sync_module, "MAX_OUTPUT_DOWNLOAD_BYTES", 4)
    _FakeAsyncClient.get_response = _FakeResponse(
        200, json_data={"id": "gen_123", "status": "COMPLETED", "outputUrl": "https://cdn.sync.so/out.mp4"}
    )
    _FakeAsyncClient.stream_response = _FakeStreamResponse(200, chunks=[b"aaaaa", b"bbbbb"])

    adapter = SyncAdapter()
    with pytest.raises(SyncAPIError):
        await adapter.poll("gen_123")
