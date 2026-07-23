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

# Брендинг ToonTales в правом верхнем углу. Помимо айдентики он перекрывает
# вотермарк lipsync-провайдера (Sync.so на hobbyist-тарифе вшивает "sync.so" в
# кадры), который иначе остаётся в готовом ролике. Статичный PNG накладывается
# overlay-фильтром — без шрифтов/текста в рантайме (надёжно в slim-контейнере).
BRAND_OVERLAY_PATH = Path(__file__).resolve().parent.parent / "assets" / "brand_overlay.png"
BRAND_MARGIN_RIGHT = 6
BRAND_MARGIN_TOP = 12

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
    # voiceover-режим: отдельная озвучка кладётся поверх немого видео. scene_duration —
    # эталонная длина сцены (сек). Прайсинг v3: это длина ВИДЕО-клипа (фиксирована
    # выбранной длительностью ролика). Озвучка короче -> дополняется тишиной (apad),
    # длиннее -> подрезается. None -> lipsync-режим (звук уже в video_path).
    audio_path: Path | None = None
    scene_duration: float | None = None


# Максимальный freeze хвоста видео под озвучку (voiceover). Видео Runway 2..10с,
# озвучка сцены-реплики короткая — 60с с запасом гарантирует, что кадра хватит на
# всю длину аудио; лишнее отбрасывается trim'ом (кадры сверх нужного не генерируются).
MAX_FREEZE_SECONDS = 60


def probe_duration_seconds(path: Path) -> float:
    """Длительность медиафайла (сек) через ffprobe. Нужна и для подбора Runway
    duration под озвучку, и для точной нарезки сцены в composition."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise CompositionError(f"ffprobe failed (code {proc.returncode}): {proc.stderr[-500:]}")
    raw = proc.stdout.strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise CompositionError(f"ffprobe returned non-numeric duration: {raw!r}") from exc


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
    brand_overlay_path: Path | None = BRAND_OVERLAY_PATH,
) -> Path:
    """Склеивает клипы сцен, опционально накладывает фоновую музыку и субтитры,
    нормализует к 9:16 MP4 и наносит брендинг ToonTales (см. BRAND_OVERLAY_PATH).

    Два режима на клип: lipsync (audio_path=None — звук уже в видео, берётся дорожка
    [i:a]) и voiceover (audio_path задан — отдельная озвучка кладётся поверх немого
    видео, длина сцены = scene_duration, видео короче -> freeze хвоста, длиннее ->
    тримминг). Режим определяется наличием audio_path у клипов."""
    if not scenes:
        raise CompositionError("no scenes to compose")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    voiceover = any(scene.audio_path is not None for scene in scenes)

    inputs: list[str] = []
    for scene in scenes:
        inputs += ["-i", str(scene.video_path)]

    audio_input_index: dict[int, int] = {}
    next_input_index = len(scenes)
    if voiceover:
        for i, scene in enumerate(scenes):
            if scene.audio_path is None or scene.scene_duration is None:
                # Смешанный режим (часть клипов с озвучкой, часть без) не поддержан —
                # режим глобальный по run (settings.lipsync_enabled).
                raise CompositionError(
                    f"voiceover clip {i} requires both audio_path and scene_duration"
                )
            inputs += ["-i", str(scene.audio_path)]
            audio_input_index[i] = next_input_index
            next_input_index += 1

    filter_parts: list[str] = []
    for i, scene in enumerate(scenes):
        base = (
            f"[{i}:v]scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
        if voiceover:
            duration = scene.scene_duration
            filter_parts.append(
                f"{base},tpad=stop_mode=clone:stop_duration={MAX_FREEZE_SECONDS},"
                f"trim=duration={duration},setpts=PTS-STARTPTS[v{i}]"
            )
            filter_parts.append(
                f"[{audio_input_index[i]}:a]atrim=duration={duration},"
                f"asetpts=PTS-STARTPTS,apad=whole_dur={duration}[a{i}]"
            )
        else:
            filter_parts.append(f"{base}[v{i}]")

    if voiceover:
        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(scenes)))
    else:
        concat_inputs = "".join(f"[v{i}][{i}:a]" for i in range(len(scenes)))
    filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={len(scenes)}:v=1:a=1[outv][outa]"

    map_video = "[outv]"
    map_audio = "[outa]"

    extra_inputs: list[str] = []
    if background_music_path is not None:
        extra_inputs += ["-i", str(background_music_path)]
        music_index = next_input_index
        next_input_index += 1
        filter_complex += f";[outa][{music_index}:a]amix=inputs=2:duration=first:dropout_transition=2[mixedout]"
        map_audio = "[mixedout]"

    if subtitles_srt_path is not None:
        # subtitles-фильтр применяется после concat, отдельным проходом через filter_complex map.
        filter_complex += f";{map_video}subtitles={subtitles_srt_path}[subout]"
        map_video = "[subout]"

    if brand_overlay_path is not None and brand_overlay_path.exists():
        extra_inputs += ["-i", str(brand_overlay_path)]
        brand_index = next_input_index
        next_input_index += 1
        # eof_action=repeat: одиночный PNG-кадр держится на всю длительность ролика.
        filter_complex += (
            f";{map_video}[{brand_index}:v]"
            f"overlay=W-w-{BRAND_MARGIN_RIGHT}:{BRAND_MARGIN_TOP}:eof_action=repeat[branded]"
        )
        map_video = "[branded]"

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
