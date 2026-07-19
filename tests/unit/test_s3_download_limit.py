"""review.md §10 P1: FFmpeg-входы должны быть ограничены по размеру до скачивания."""

import pytest

from toontales_ai.storage import s3


class _FakeS3Client:
    def __init__(self, content_length: int):
        self._content_length = content_length
        self.downloaded = False

    def head_object(self, *, Bucket, Key):
        return {"ContentLength": self._content_length}

    def download_file(self, Bucket, Key, Filename):
        self.downloaded = True


def test_download_to_path_rejects_object_over_limit(monkeypatch, tmp_path):
    fake_client = _FakeS3Client(content_length=10 * 1024 * 1024)
    monkeypatch.setattr(s3, "_s3_client", fake_client)

    with pytest.raises(s3.DownloadSizeExceededError):
        s3.download_to_path("some/key", tmp_path / "out.mp4", max_bytes=1024 * 1024)

    assert fake_client.downloaded is False


def test_download_to_path_allows_object_within_limit(monkeypatch, tmp_path):
    fake_client = _FakeS3Client(content_length=512)
    monkeypatch.setattr(s3, "_s3_client", fake_client)

    s3.download_to_path("some/key", tmp_path / "out.mp4", max_bytes=1024 * 1024)

    assert fake_client.downloaded is True


def test_download_to_path_skips_head_check_without_max_bytes(monkeypatch, tmp_path):
    fake_client = _FakeS3Client(content_length=10**12)
    monkeypatch.setattr(s3, "_s3_client", fake_client)

    s3.download_to_path("some/key", tmp_path / "out.mp4")  # без max_bytes — не должен упасть

    assert fake_client.downloaded is True
