"""RunwayImageAdapter — реальный vendor HTTP API (Runway gen4_image), мокается на
уровне httpx.AsyncClient (CLAUDE.md: моки уместны для внешних/медленных зависимостей).
Живая проверка против настоящего Runway API — ручная, вне автоматического набора
(нет ключа для CI)."""

from pathlib import Path

import httpx
import pytest

from toontales_ai.adapters.base import StageInput
from toontales_ai.adapters.image import runway as runway_image_module
from toontales_ai.adapters.image.runway import RunwayImageAdapter, RunwayImageAPIError, RunwayImageConfigError
from toontales_ai.config import settings as settings_module
from toontales_ai.domain.enums import ProviderJobStatus


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _configure_runway(monkeypatch):
    monkeypatch.setenv("TOONTALES_RUNWAY_API_KEY", "key-1")
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
    monkeypatch.setenv("TOONTALES_RUNWAY_API_KEY", "")
    settings_module.get_settings.cache_clear()

    with pytest.raises(RunwayImageConfigError):
        RunwayImageAdapter()


async def test_submit_sends_expected_body_and_returns_queued(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(200, json_data={"id": "task_123", "status": "PENDING"})

    adapter = RunwayImageAdapter()
    submission = await adapter.submit(
        StageInput(
            task_id="t1",
            scene_id="s1",
            payload={"image_prompt": "a fox in a forest", "mood_notes": "mysterious"},
        ),
        idempotency_key="run1:image_generation:s1:v1",
    )

    assert submission.provider_job_id == "task_123"
    assert submission.status == ProviderJobStatus.QUEUED
    assert submission.result is None

    body = _FakeAsyncClient.last_post_call["json"]
    assert body["model"] == "gen4_image"
    assert body["ratio"] == runway_image_module.VERTICAL_RATIO
    assert "a fox in a forest" in body["promptText"]
    assert "mysterious" in body["promptText"]
    assert _FakeAsyncClient.last_post_call["headers"]["Authorization"] == "Bearer key-1"


async def test_submit_rejects_empty_prompt(monkeypatch):
    adapter = RunwayImageAdapter()
    with pytest.raises(RunwayImageAPIError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id="s1", payload={}),
            idempotency_key="k",
        )


@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_submit_raises_transient_error_for_429_and_5xx(monkeypatch, status_code):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(status_code, text="overloaded")

    adapter = RunwayImageAdapter()
    with pytest.raises(runway_image_module.RunwayImageTransientError):
        await adapter.submit(
            StageInput(task_id="t1", scene_id="s1", payload={"image_prompt": "a fox"}),
            idempotency_key="k",
        )


async def test_submit_raises_plain_api_error_for_4xx(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.post_response = _FakeResponse(400, text="bad request")

    adapter = RunwayImageAdapter()
    with pytest.raises(RunwayImageAPIError) as exc_info:
        await adapter.submit(
            StageInput(task_id="t1", scene_id="s1", payload={"image_prompt": "a fox"}),
            idempotency_key="k",
        )
    assert not isinstance(exc_info.value, runway_image_module.RunwayImageTransientError)


@pytest.mark.parametrize(
    "runway_status,expected",
    [
        ("PENDING", ProviderJobStatus.QUEUED),
        ("THROTTLED", ProviderJobStatus.QUEUED),
        ("RUNNING", ProviderJobStatus.PROCESSING),
        ("SOME_FUTURE_STATUS", ProviderJobStatus.PROCESSING),
    ],
)
async def test_poll_maps_non_terminal_statuses(monkeypatch, runway_status, expected):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(200, json_data={"id": "task_123", "status": runway_status})

    adapter = RunwayImageAdapter()
    result = await adapter.poll("task_123")

    assert result.status == expected


async def test_poll_maps_cancelled_to_failed(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(200, json_data={"id": "task_123", "status": "CANCELLED"})

    adapter = RunwayImageAdapter()
    result = await adapter.poll("task_123")

    assert result.status == ProviderJobStatus.FAILED
    assert result.error_code == "CANCELLED"


async def test_poll_maps_failed_with_failure_reason(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(
        200, json_data={"id": "task_123", "status": "FAILED", "failure": "bad prompt", "failureCode": "INVALID_INPUT"}
    )

    adapter = RunwayImageAdapter()
    result = await adapter.poll("task_123")

    assert result.status == ProviderJobStatus.FAILED
    assert result.error_code == "INVALID_INPUT"
    assert result.error_detail == "bad prompt"


async def test_poll_succeeded_downloads_and_uploads_output(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(
        200, json_data={"id": "task_123", "status": "SUCCEEDED", "output": ["https://cdn.runway/out.png"]}
    )
    _FakeAsyncClient.stream_response = _FakeStreamResponse(200, chunks=[b"fake", b"-png-", b"bytes"])

    uploaded: dict = {}

    def _fake_upload_from_path(source_path, storage_key: str, *, content_type: str) -> None:
        uploaded["data"] = Path(source_path).read_bytes()
        uploaded["storage_key"] = storage_key
        uploaded["content_type"] = content_type

    monkeypatch.setattr(runway_image_module, "upload_from_path", _fake_upload_from_path)

    adapter = RunwayImageAdapter()
    result = await adapter.poll("task_123")

    assert result.status == ProviderJobStatus.SUCCEEDED
    assert result.artifacts[0]["storage_key"] == "runway-image/task_123.png"
    assert result.artifacts[0]["size_bytes"] == len(b"fake-png-bytes")
    assert uploaded["data"] == b"fake-png-bytes"
    assert uploaded["content_type"] == "image/png"


async def test_poll_succeeded_with_empty_output_is_failed(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.get_response = _FakeResponse(200, json_data={"id": "task_123", "status": "SUCCEEDED", "output": []})

    adapter = RunwayImageAdapter()
    result = await adapter.poll("task_123")

    assert result.status == ProviderJobStatus.FAILED
    assert result.error_code == "NO_OUTPUT"


async def test_download_output_enforces_size_limit(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(runway_image_module, "MAX_OUTPUT_DOWNLOAD_BYTES", 4)
    _FakeAsyncClient.get_response = _FakeResponse(
        200, json_data={"id": "task_123", "status": "SUCCEEDED", "output": ["https://cdn.runway/out.png"]}
    )
    _FakeAsyncClient.stream_response = _FakeStreamResponse(200, chunks=[b"aaaaa", b"bbbbb"])

    adapter = RunwayImageAdapter()
    with pytest.raises(RunwayImageAPIError):
        await adapter.poll("task_123")
