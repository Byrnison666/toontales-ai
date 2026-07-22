"""Реальный вызов ffmpeg (skip, если бинарник недоступен). Генерирует синтетические
клипы через lavfi вместо реальных provider-артефактов — так composition-слой
тестируем изолированно от S3/vendor-адаптеров."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from toontales_ai.storage.composition import (
    CompositionError,
    SceneClip,
    compose_scenes,
    probe_duration_seconds,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg не установлен в этом окружении")


def _make_synthetic_clip(path: Path, *, duration: float, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi", "-i", f"color=c={color}:s=640x360:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
        capture_output=True,
    )


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def test_compose_scenes_produces_valid_concatenated_mp4(tmp_path: Path):
    clip_a = tmp_path / "scene_0.mp4"
    clip_b = tmp_path / "scene_1.mp4"
    _make_synthetic_clip(clip_a, duration=1.0, color="red")
    _make_synthetic_clip(clip_b, duration=1.5, color="blue")

    output_path = tmp_path / "final.mp4"
    result_path = compose_scenes(
        [SceneClip(video_path=clip_a), SceneClip(video_path=clip_b)],
        output_path=output_path,
    )

    assert result_path.exists()
    duration = _ffprobe_duration(result_path)
    # Суммарная длительность двух сцен (~2.5s) с допуском на контейнерные накладные расходы.
    assert 2.0 < duration < 3.0


def _make_silent_clip(path: Path, *, duration: float, color: str) -> None:
    """Немое видео (без аудиодорожки) — вход voiceover-режима."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi", "-i", f"color=c={color}:s=640x360:d={duration}",
            "-c:v", "libx264", str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_audio(path: Path, *, duration: float, freq: int = 440) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", str(path)],
        check=True,
        capture_output=True,
    )


def test_probe_duration_seconds(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    _make_audio(audio, duration=2.0)
    assert 1.8 < probe_duration_seconds(audio) < 2.2


def test_voiceover_scene_length_matches_audio_freezing_short_video(tmp_path: Path):
    # Видео короче озвучки -> freeze хвоста до длины аудио, речь не режется.
    video = tmp_path / "scene_0.mp4"
    audio = tmp_path / "scene_0.mp3"
    _make_silent_clip(video, duration=1.0, color="red")
    _make_audio(audio, duration=2.5)

    output_path = tmp_path / "final.mp4"
    compose_scenes(
        [SceneClip(video_path=video, audio_path=audio, audio_duration=2.5)],
        output_path=output_path,
    )
    assert output_path.exists()
    # Сцена длится по озвучке (~2.5s), а не по видео (1.0s).
    assert 2.3 < _ffprobe_duration(output_path) < 2.8


def test_voiceover_trims_video_longer_than_audio(tmp_path: Path):
    # Видео длиннее озвучки -> обрезается до длины аудио.
    video = tmp_path / "scene_0.mp4"
    audio = tmp_path / "scene_0.mp3"
    _make_silent_clip(video, duration=4.0, color="blue")
    _make_audio(audio, duration=1.5)

    output_path = tmp_path / "final.mp4"
    compose_scenes(
        [SceneClip(video_path=video, audio_path=audio, audio_duration=1.5)],
        output_path=output_path,
    )
    assert 1.3 < _ffprobe_duration(output_path) < 1.8


def test_voiceover_requires_audio_duration(tmp_path: Path):
    video = tmp_path / "scene_0.mp4"
    audio = tmp_path / "scene_0.mp3"
    _make_silent_clip(video, duration=1.0, color="green")
    _make_audio(audio, duration=1.0)
    with pytest.raises(CompositionError):
        compose_scenes(
            [SceneClip(video_path=video, audio_path=audio, audio_duration=None)],
            output_path=tmp_path / "out.mp4",
        )


def test_compose_scenes_rejects_empty_input(tmp_path: Path):
    with pytest.raises(CompositionError):
        compose_scenes([], output_path=tmp_path / "out.mp4")


def test_compose_scenes_with_background_music(tmp_path: Path):
    clip = tmp_path / "scene_0.mp4"
    _make_synthetic_clip(clip, duration=1.0, color="green")
    music = tmp_path / "music.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-f", "lavfi", "-i", "sine=frequency=220:duration=1.0", str(music)],
        check=True,
        capture_output=True,
    )

    output_path = tmp_path / "final_with_music.mp4"
    result_path = compose_scenes(
        [SceneClip(video_path=clip)],
        output_path=output_path,
        background_music_path=music,
    )

    assert result_path.exists()
    assert _ffprobe_duration(result_path) > 0.5
