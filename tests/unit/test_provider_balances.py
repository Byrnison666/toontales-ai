"""Разбор ответов провайдеров и пороги «мало» для админ-сводки остатков."""

import httpx
import pytest

from toontales_ai.orchestration import provider_balances as pb


class _FakeResp:
    def __init__(self, status_code: int, data=None, text: str = ""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        return self._data


class _FakeClient:
    resp: _FakeResp | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        return _FakeClient.resp


@pytest.fixture
def fake_http(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(pb.get_settings(), "runway_api_key", "k")
    monkeypatch.setattr(pb.get_settings(), "elevenlabs_api_key", "k")
    return _FakeClient


async def test_runway_balance_ok_and_low_flag(fake_http):
    fake_http.resp = _FakeResp(200, {"creditBalance": 630})
    entry = await pb._runway()
    assert entry["available"] is True
    assert entry["balance"] == 630
    assert entry["balance_usd"] == "6.30"  # 630 × $0.01
    assert entry["low"] is True  # < 1000 порог по умолчанию
    assert "с видео" in entry["note"]


async def test_runway_balance_ok_not_low(fake_http, monkeypatch):
    monkeypatch.setattr(pb.get_settings(), "runway_low_credits_threshold", 100)
    fake_http.resp = _FakeResp(200, {"creditBalance": 630})
    entry = await pb._runway()
    assert entry["low"] is False


async def test_runway_non_200_sets_error(fake_http):
    fake_http.resp = _FakeResp(500, text="boom")
    entry = await pb._runway()
    assert entry["available"] is False
    assert "500" in entry["error"]


async def test_elevenlabs_401_hints_permission(fake_http):
    fake_http.resp = _FakeResp(401, text="missing perms")
    entry = await pb._elevenlabs()
    assert entry["available"] is False
    assert "user_read" in entry["error"]


async def test_elevenlabs_remaining_computed(fake_http):
    fake_http.resp = _FakeResp(
        200, {"character_limit": 100_000, "character_count": 30_000, "next_character_count_reset_unix": 1_800_000_000}
    )
    entry = await pb._elevenlabs()
    assert entry["available"] is True
    assert entry["balance"] == 70_000
    assert entry["low"] is False  # 70k > 20k порог
    assert entry["reset_at"] is not None


def test_anthropic_is_console_only():
    entry = pb._anthropic()
    assert entry["available"] is False
    assert "console.anthropic.com" in entry["console_url"]
