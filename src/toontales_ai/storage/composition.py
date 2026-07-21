"""FFmpeg composition (v2.md stage 6): склейка сцен, аудио, субтитры, рендер
итогового MP4 9:16. Работает над локальными файлами — загрузка из/выгрузка в S3
делается отдельно вызывающей стороной (workers/tasks.py), чтобы сам ffmpeg-слой
был тестируем без реального object storage.

Sandbox (review.md §10, пробел "FFmpeg обрабатывает недоверенные файлы без
требований к sandbox"): CPU/RAM/disk rlimits через preexec_fn, wall-clock timeout,
никаких сетевых протоколов — ffmpeg получает только уже скачанные локальные файлы
(protocol whitelist ограничен file). Полная изоляция сети процесса потребовала бы
контейнера/namespace и не входит в объём текущего шага — явно отмечено ниже."""

import resource
import subprocess
from dataclasses import dataclass
from pathlib import Path

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920  # 9:16

# Живой e2e-прогон с реальным STORYBOARD-адаптером (5 сцен, v2.md ориентир
# "до 5-6 сцен") вскрыл: прежние 120с/100с CPU были откалиброваны под 2-сценовый
# stub и x264-кодирование 5 клипов упиралось в MAX_CPU_SECONDS ещё до завершения
# concat — subprocess получал SIGKILL (soft==hard limit, grace-периода нет).
# Подняты пропорционально MAX_ASSUMED_SCENES=6 (pipeline_async.py).
DEFAULT_TIMEOUT_SECONDS = 400
MAX_CPU_SECONDS = 500
MAX_OUTPUT_FILE_BYTES = 500 * 1024 * 1024  # 500 MiB — защита от decompression bomb на выходе


class CompositionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SceneClip:
    video_path: Path
    audio_path: Path | None = None


def _limit_resources() -> None:
    """preexec_fn для subprocess.Popen: rlimits на дочерний ffmpeg-процесс.

    RLIMIT_AS сознательно НЕ используется: x264 — многопоточный кодировщик,
    его суммарное виртуальное адресное пространство (shared-библиотеки, стеки
    потоков, mmap) легко превышает разумный лимит ещё до реальной обработки
    кадров, что ломает кодирование даже на маленьких клипах. Для полноценного
    ограничения RAM нужны cgroups/контейнер на уровне воркера, а не rlimit —
    это инфраструктурная задача вне текущего шага."""
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_SECONDS, MAX_CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_FILE_BYTES, MAX_OUTPUT_FILE_BYTES))


def _run_ffmpeg(args: list[str], *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    cmd = ["ffmpeg", "-y", "-nostdin", "-protocol_whitelist", "file,pipe", *args]
    try:
        proc = subprocess.run(
            cmd,
            preexec_fn=_limit_resources,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompositionError(f"ffmpeg timed out after {timeout_seconds}s") from exc

    if proc.returncode != 0:
        raise CompositionError(f"ffmpeg failed (code {proc.returncode}): {proc.stderr[-2000:]}")


def compose_scenes(
    scenes: list[SceneClip],
    *,
    output_path: Path,
    subtitles_srt_path: Path | None = None,
    background_music_path: Path | None = None,
) -> Path:
    """Склеивает клипы сцен (каждый уже содержит собственную озвучку/lipsync-результат),
    опционально накладывает фоновую музыку и субтитры, нормализует к 9:16 MP4."""
    if not scenes:
        raise CompositionError("no scenes to compose")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    inputs: list[str] = []
    filter_parts: list[str] = []
    for i, scene in enumerate(scenes):
        inputs += ["-i", str(scene.video_path)]
        filter_parts.append(
            f"[{i}:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]"
        )

    concat_inputs = "".join(f"[v{i}][{i}:a]" for i in range(len(scenes)))
    filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={len(scenes)}:v=1:a=1[outv][outa]"

    map_video = "[outv]"
    map_audio = "[outa]"

    extra_inputs: list[str] = []
    if background_music_path is not None:
        extra_inputs += ["-i", str(background_music_path)]
        music_index = len(scenes)
        filter_complex += f";[outa][{music_index}:a]amix=inputs=2:duration=first:dropout_transition=2[mixedout]"
        map_audio = "[mixedout]"

    if subtitles_srt_path is not None:
        # subtitles-фильтр применяется после concat, отдельным проходом через filter_complex map.
        filter_complex += f";{map_video}subtitles={subtitles_srt_path}[subout]"
        map_video = "[subout]"

    args = [
        *inputs,
        *extra_inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        map_video,
        "-map",
        map_audio,
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(args)
    return output_path
