"""Celery-задачи: submit провайдеру и polling. Только retry для классифицированных
transient-ошибок (review.md §7) — на Celery-уровне ретраится связь с провайдером,
на domain-уровне (pipeline_sync.complete_task) — retry_count/RETRY_SCHEDULED
для провайдер-репортед failure. Единый безопасный runner на задачу: свой event
loop и своя sync Session на каждый вызов (review.md §7 — не переиспользуется
между задачами)."""

import asyncio
import math
import random
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import redis
from celery import Task as CeleryTask
from sqlalchemy import select

from toontales_ai.adapters.base import ProviderJobResult, ProviderSubmission, StageInput
from toontales_ai.adapters.image.runway import RunwayImageTransientError
from toontales_ai.adapters.lipsync.sync_so import SyncTransientError
from toontales_ai.adapters.registry import get_adapter
from toontales_ai.adapters.storyboard.anthropic import AnthropicTransientError
from toontales_ai.adapters.video.runway import (
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    RunwayTransientError,
)
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import MediaKind, ProviderJobStatus, Stage, TaskStatus
from toontales_ai.domain.models import MediaAsset, Scene, Task
from toontales_ai.orchestration import provider_semaphore
from toontales_ai.orchestration.pipeline_sync import complete_task
from toontales_ai.storage.composition import (
    CompositionError,
    SceneClip,
    compose_scenes,
    probe_duration_seconds,
)
from toontales_ai.storage.db import SyncSessionLocal
from toontales_ai.storage.s3 import DownloadSizeExceededError, download_to_path, presigned_get_url, upload_from_path
from toontales_ai.workers.celery_app import celery_app

_SEMAPHORE_PROVIDER_BY_STAGE = provider_semaphore.SEMAPHORE_PROVIDER_BY_STAGE


def _semaphore_limit(stage: Stage) -> int:
    if stage == Stage.LIPSYNC:
        # max(1, ...) — защита от TOONTALES_SYNC_MAX_CONCURRENCY=0/отрицательного
        # (иначе acquire всегда бы отказывал и задача вечно requeue'илась бы
        # каждые ~несколько секунд — hot-loop; admission-control-ревью).
        return max(1, get_settings().sync_max_concurrency)
    return 1


def _release_semaphore_if_held(task_stage: Stage, task_id: str) -> None:
    provider = _SEMAPHORE_PROVIDER_BY_STAGE.get(task_stage)
    if provider is not None:
        provider_semaphore.release_slot(provider=provider, holder=task_id)


# Задержка requeue при занятом слоте/сбое Redis: базовые ~2с + случайный jitter,
# чтобы N ожидающих lipsync-задач (и at-least-once дубли) не долбили Redis/Celery
# синхронным штормом с одинаковым интервалом (admission-control-ревью).
_SEMAPHORE_RETRY_BASE_SECONDS = 2


def _semaphore_retry_delay() -> float:
    return _SEMAPHORE_RETRY_BASE_SECONDS + random.uniform(0, _SEMAPHORE_RETRY_BASE_SECONDS)

# Классы ошибок, которые считаются transient и подлежат Celery-level retry.
# httpx.TransportError — общий базовый класс сетевых сбоев httpx (ConnectError,
# {Connect,Read,Write,Pool}Timeout и т.п.) при вызове реальных vendor-адаптеров
# (напр. ElevenLabsAdapter) — не подклассы builtin ConnectionError/TimeoutError.
# RunwayTransientError/RunwayImageTransientError/SyncTransientError/AnthropicTransientError —
# 429/5xx от Runway/Sync.so/Anthropic (перегрузка/сбой сервиса, а не ошибка запроса) —
# не должны сжигать domain-level retry_count наравне с permanent-ошибками (invalid input и т.п.).
#
# Известный принятый риск (аудит финансовой корректности, не устранён): если
# httpx.TransportError/таймаут случится ПОСЛЕ того как провайдер принял запрос
# (напр. таймаут на чтение ответа, не на запись), но ДО того как мы сохранили
# provider_job_id, Celery-retry вызовет adapter.submit() заново с тем же
# idempotency_key — а сам провайдер это поле не учитывает как ключ дедупликации
# (ни Runway, ни ElevenLabs, ни Sync.so, ни Anthropic не документируют
# server-side idempotency-key support). Возможна повторная платная генерация
# у провайдера. Полное решение требует idempotency-key поддержки на стороне
# каждого провайдера — вне объёма текущего шага.
TRANSIENT_ERRORS = (
    ConnectionError,
    TimeoutError,
    httpx.TransportError,
    RunwayTransientError,
    RunwayImageTransientError,
    SyncTransientError,
    AnthropicTransientError,
)

MAX_POLL_BACKOFF_SECONDS = 60

# Лимит на скачиваемый per-scene клип перед FFmpeg (review.md §10 P1): недоверенный/
# подменённый S3-объект не должен заполнить /tmp или спровоцировать OOM до того, как
# сработает лимит выходного файла composition.MAX_OUTPUT_FILE_BYTES.
MAX_COMPOSITION_INPUT_BYTES = 500 * 1024 * 1024


def _exponential_backoff(attempt: int, base: int = 2, cap: int = MAX_POLL_BACKOFF_SECONDS) -> int:
    return min(cap, base * (2**attempt))


def _unique_scene_asset_key(session, scene_id, *, kind: MediaKind, stage: Stage) -> str:
    """storage_key единственного MediaAsset сцены заданного kind/stage. Fail-fast при
    отсутствии/неоднозначности (review.md §10 P2: недетерминированный выбор артефакта
    не должен решаться молча — напр. thumbnail вместо видео)."""
    candidates = session.execute(
        select(MediaAsset)
        .join(Task, Task.id == MediaAsset.task_id)
        .where(MediaAsset.scene_id == scene_id, MediaAsset.kind == kind, Task.stage == stage)
    ).scalars().all()
    if not candidates:
        raise CompositionError(f"no {stage.value} {kind.value} asset for scene {scene_id}")
    if len(candidates) > 1:
        raise CompositionError(
            f"ambiguous {stage.value} {kind.value} asset for scene {scene_id}: "
            f"{len(candidates)} candidates, expected exactly one"
        )
    return candidates[0].storage_key


def _run_composition(session, task: Task) -> ProviderSubmission:
    """Реальная FFmpeg-сборка (v2.md stage 6): скачивает per-scene "финальный клип
    сцены" из DAG (LIPSYNC в lipsync-режиме, VIDEO в voiceover — см. STAGE_PREDECESSORS),
    склеивает и загружает результат в S3. В voiceover дополнительно тянет AUDIO-ассет
    сцены — озвучка кладётся поверх немого видео (длина сцены = длине озвучки)."""
    lipsync_enabled = get_settings().lipsync_enabled
    video_source_stage = Stage.LIPSYNC if lipsync_enabled else Stage.VIDEO

    scenes = session.execute(
        select(Scene).where(Scene.generation_run_id == task.run_id).order_by(Scene.scene_index)
    ).scalars().all()
    if not scenes:
        raise CompositionError(f"run {task.run_id} has no scenes to compose")

    with tempfile.TemporaryDirectory(prefix="toontales-compose-") as tmp:
        tmp_dir = Path(tmp)
        clips: list[SceneClip] = []
        for scene in scenes:
            video_key = _unique_scene_asset_key(session, scene.id, kind=MediaKind.VIDEO, stage=video_source_stage)
            video_path = tmp_dir / f"scene_{scene.scene_index}.mp4"
            try:
                download_to_path(video_key, video_path, max_bytes=MAX_COMPOSITION_INPUT_BYTES)
            except DownloadSizeExceededError as exc:
                raise CompositionError(str(exc)) from exc

            if lipsync_enabled:
                clips.append(SceneClip(video_path=video_path))
                continue

            # Voiceover: немое видео + отдельная озвучка, длина сцены = длине озвучки.
            audio_key = _unique_scene_asset_key(session, scene.id, kind=MediaKind.AUDIO, stage=Stage.AUDIO)
            audio_path = tmp_dir / f"scene_{scene.scene_index}.audio"
            try:
                download_to_path(audio_key, audio_path, max_bytes=MAX_COMPOSITION_INPUT_BYTES)
            except DownloadSizeExceededError as exc:
                raise CompositionError(str(exc)) from exc
            clips.append(
                SceneClip(
                    video_path=video_path,
                    audio_path=audio_path,
                    audio_duration=probe_duration_seconds(audio_path),
                )
            )

        output_path = tmp_dir / "final.mp4"
        compose_scenes(clips, output_path=output_path)

        final_storage_key = f"runs/{task.run_id}/final_render/{task.id}.mp4"
        upload_from_path(output_path, final_storage_key, content_type="video/mp4")
        size_bytes = output_path.stat().st_size

    result = ProviderJobResult(
        provider_job_id=None,
        status=ProviderJobStatus.SUCCEEDED,
        artifacts=({"storage_key": final_storage_key, "content_type": "video/mp4", "size_bytes": size_bytes},),
    )
    return ProviderSubmission(provider_job_id=None, status=ProviderJobStatus.SUCCEEDED, result=result)


def _failed_submission(error_code: str, error_detail: str) -> ProviderSubmission:
    """Единая точка построения FAILED ProviderSubmission — используется и для
    доменных ошибок composition, и для любых прочих исключений во время submit,
    чтобы они шли через complete_task() и его retry_count/RETRY_SCHEDULED/release
    логику вместо того, чтобы утекать из Celery-задачи необработанными (P0-баг:
    раньше ловился только CompositionError, а botocore/OSError/FileNotFoundError
    оставляли Task навечно в SUBMITTING без release hold)."""
    return ProviderSubmission(
        provider_job_id=None,
        status=ProviderJobStatus.FAILED,
        result=ProviderJobResult(
            provider_job_id=None,
            status=ProviderJobStatus.FAILED,
            error_code=error_code,
            error_detail=error_detail,
        ),
    )


def _scene_audio_duration_seconds(session, scene_id) -> int:
    """Длина озвучки сцены в секундах, ceil + кламп в Runway-диапазон 2..10 (voiceover:
    видео генерируется под озвучку). Значение кладётся и в Runway duration, и в
    task.input_snapshot для точного real_cost — поэтому клампим здесь, чтобы совпало
    с тем, что Runway фактически отрендерит."""
    audio_key = _unique_scene_asset_key(session, scene_id, kind=MediaKind.AUDIO, stage=Stage.AUDIO)
    with tempfile.TemporaryDirectory(prefix="toontales-audioprobe-") as td:
        tmp_path = Path(td) / "audio"
        try:
            download_to_path(audio_key, tmp_path, max_bytes=MAX_COMPOSITION_INPUT_BYTES)
        except DownloadSizeExceededError as exc:
            raise CompositionError(str(exc)) from exc
        duration = probe_duration_seconds(tmp_path)
    return max(MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, math.ceil(duration)))


def _build_stage_input(session, task: Task) -> StageInput:
    payload: dict = {}
    if task.stage == Stage.STORYBOARD:
        payload = task.input_snapshot or {}
    elif task.scene_id is not None:
        scene = session.get(Scene, task.scene_id)
        if scene is not None:
            payload = {
                "script_text": scene.script_text,
                "image_prompt": scene.image_prompt,
                "camera_movement": scene.camera_movement,
                "mood_notes": scene.mood_notes,
            }
            if task.stage == Stage.VIDEO:
                # v2.md stage 3: "Вход stage: source image, motion prompt, camera
                # movement instructions..." — реальному video-адаптеру (RunwayAdapter)
                # нужен HTTPS URL уже сгенерированного изображения сцены, а не только
                # текстовые поля. Раньше этого поля не было вовсе — не имело значения
                # для стаб-адаптеров, но блокировало реальную интеграцию.
                image_assets = session.execute(
                    select(MediaAsset)
                    .join(Task, Task.id == MediaAsset.task_id)
                    .where(
                        MediaAsset.scene_id == scene.id,
                        MediaAsset.kind == MediaKind.IMAGE,
                        Task.stage == Stage.IMAGE,
                    )
                ).scalars().all()
                if len(image_assets) > 1:
                    # Task.idempotency_key уникален на (run, stage, scene) — при
                    # нормальной работе тут ровно один IMAGE Task на сцену, значит и
                    # один MediaAsset. Больше одного означает, что провайдер вернул
                    # несколько image-артефактов в одном результате (см. аналогичный
                    # fail-fast для lipsync-артефакта в _run_composition) — явная
                    # ошибка вместо молчаливого выбора "последнего по created_at".
                    raise ValueError(
                        f"ambiguous IMAGE asset for scene {scene.id}: "
                        f"{len(image_assets)} candidates, expected exactly one"
                    )
                if image_assets:
                    payload["source_image_url"] = presigned_get_url(image_assets[0].storage_key)
                if not get_settings().lipsync_enabled:
                    # Voiceover: VIDEO — join на (IMAGE, AUDIO); длину видео подгоняем
                    # под уже готовую озвучку сцены (Runway duration = ceil(audio), 2..10).
                    payload["duration_seconds"] = _scene_audio_duration_seconds(session, scene.id)
            elif task.stage == Stage.LIPSYNC:
                # LIPSYNC — join-стадия (STAGE_PREDECESSORS: требует VIDEO и AUDIO).
                # Реальному адаптеру (SyncAdapter) нужны HTTPS URL уже готовых
                # видео- и аудио-артефактов сцены, а не текстовые поля сцены.
                for stage, kind, field_name in (
                    (Stage.VIDEO, MediaKind.VIDEO, "source_video_url"),
                    (Stage.AUDIO, MediaKind.AUDIO, "source_audio_url"),
                ):
                    assets = session.execute(
                        select(MediaAsset)
                        .join(Task, Task.id == MediaAsset.task_id)
                        .where(MediaAsset.scene_id == scene.id, MediaAsset.kind == kind, Task.stage == stage)
                    ).scalars().all()
                    if len(assets) > 1:
                        # Тот же fail-fast, что и для IMAGE выше (review.md §10 P2):
                        # неоднозначный выбор артефакта не должен решаться молча.
                        raise ValueError(
                            f"ambiguous {kind.value} asset for scene {scene.id}: "
                            f"{len(assets)} candidates, expected exactly one"
                        )
                    if assets:
                        payload[field_name] = presigned_get_url(assets[0].storage_key)
    return StageInput(task_id=str(task.id), scene_id=str(task.scene_id) if task.scene_id else None, payload=payload)


@celery_app.task(
    name="toontales_ai.workers.tasks.process_task",
    bind=True,
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=MAX_POLL_BACKOFF_SECONDS,
    retry_jitter=True,
    max_retries=5,
)
def process_task(self: CeleryTask, task_id: str) -> None:
    with SyncSessionLocal() as session:
        task = session.execute(select(Task).where(Task.id == uuid.UUID(task_id)).with_for_update()).scalar_one_or_none()
        if task is None or task.status not in (TaskStatus.PENDING, TaskStatus.RETRY_SCHEDULED):
            return  # уже обработан или больше не существует — идемпотентный no-op

        # Admission control ДО перевода в SUBMITTING (иначе занятый слот жёг бы
        # attempt_no зря): для стадий с лимитом concurrency пытаемся занять слот.
        # Не вышло — не трогаем статус (остаётся PENDING/RETRY_SCHEDULED, guard
        # выше пропустит повторный process_task) и откладываем без обращения к API.
        semaphore_provider = _SEMAPHORE_PROVIDER_BY_STAGE.get(task.stage)
        if semaphore_provider is not None:
            try:
                acquired = provider_semaphore.acquire_slot(
                    provider=semaphore_provider, holder=task_id, limit=_semaphore_limit(task.stage)
                )
            except redis.RedisError:
                # P0 (admission-control-ревью): RedisError не входит в TRANSIENT_ERRORS,
                # а acquire вызывается ДО attempt_no++ — необработанное исключение
                # здесь при task_acks_on_failure_or_timeout=True (Celery default)
                # заакнуло бы задачу навсегда (reconcile игнорирует attempt_no=0).
                # Транзиентный сбой Redis — просто requeue без потери задачи.
                session.rollback()
                process_task.apply_async(args=[task_id], countdown=_semaphore_retry_delay())
                return
            if not acquired:
                session.rollback()
                process_task.apply_async(args=[task_id], countdown=_semaphore_retry_delay())
                return

        task.status = TaskStatus.SUBMITTING
        task.attempt_no += 1
        task.celery_task_id = self.request.id
        task_stage = task.stage  # для release после закрытия сессии (task станет detached)
        session.commit()

        try:
            # Внутри try: _build_stage_input может бросить (напр. неоднозначный
            # IMAGE MediaAsset для VIDEO-стадии) — раньше вызывалась до try/except
            # и такая ошибка утекала из Celery-задачи необработанной, минуя
            # domain-level FAILED/retry_count путь ниже.
            stage_input = _build_stage_input(session, task)
            if task.stage == Stage.VIDEO and "duration_seconds" in stage_input.payload:
                # Voiceover: сохраняем фактическую длину видео (= озвучке) для real_cost —
                # Runway её в poll не возвращает (см. pipeline_sync.complete_task).
                task.input_snapshot = {**(task.input_snapshot or {}), "duration_seconds": stage_input.payload["duration_seconds"]}
                session.commit()
            if task.stage == Stage.COMPOSITION:
                # Composition — локальный FFmpeg-слой, не внешний provider adapter (v2.md stage 6).
                try:
                    submission = _run_composition(session, task)
                except CompositionError as exc:
                    submission = _failed_submission("COMPOSITION_FAILED", str(exc))
            else:
                adapter = get_adapter(task.stage)
                submission = asyncio.run(adapter.submit(stage_input, idempotency_key=task.idempotency_key))
        except TRANSIENT_ERRORS:
            # Известная transient-ошибка (сеть/таймаут) — возвращаем Task в PENDING,
            # иначе Celery-level retry (autoretry_for) наткнётся на guard в начале
            # функции (status not in PENDING/RETRY_SCHEDULED), станет no-op'ом, и Task
            # навсегда останется в SUBMITTING (P0: retry механизм не мог фактически
            # повторить попытку после первого падения).
            task.status = TaskStatus.PENDING
            session.commit()
            # submit не прошёл — провайдер запрос не принял, ничего активного у него
            # нет: отпускаем слот (реентрантный acquire при Celery-retry заберёт снова),
            # чтобы занятый слот не блокировал другие сцены пока ждём backoff.
            _release_semaphore_if_held(task_stage, task_id)
            raise
        except Exception as exc:
            # Любая иная ошибка (botocore/S3, отсутствующий ffmpeg, повреждённый файл
            # и т.п.) — не транзиентная в понимании Celery-level retry, но и не должна
            # оставлять Task в SUBMITTING навсегда (P0). Заворачиваем в тот же FAILED-путь,
            # что и CompositionError — дальше решает domain-level retry_count/release
            # в complete_task().
            submission = _failed_submission("TASK_EXECUTION_ERROR", str(exc))

    with SyncSessionLocal() as session:
        if submission.result is not None:
            complete_task(session, task_id=uuid.UUID(task_id), result=submission.result)
            # submit завершился синхронно (immediate result или ошибка) — задача
            # completed/failed/retry_scheduled, у провайдера ничего активного нет:
            # отпускаем слот. При retry_scheduled повторный process_task заберёт заново.
            _release_semaphore_if_held(task_stage, task_id)
        else:
            task = session.execute(select(Task).where(Task.id == uuid.UUID(task_id)).with_for_update()).scalar_one()
            task.status = TaskStatus.WAITING_PROVIDER
            task.provider_job_id = submission.provider_job_id
            task.provider_status = submission.status
            task.next_poll_at = datetime.now(timezone.utc) + timedelta(seconds=_exponential_backoff(0))
            session.commit()
            # Слот НЕ отпускаем: провайдер принял задачу, генерация идёт — держим
            # слот через серию poll_task (каждый poll обновляет TTL) до terminal.
            poll_task.apply_async(args=[task_id], countdown=_exponential_backoff(0))
            return

    _maybe_retry_scheduled(self, task_id)


@celery_app.task(
    name="toontales_ai.workers.tasks.poll_task",
    bind=True,
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=MAX_POLL_BACKOFF_SECONDS,
    retry_jitter=True,
    max_retries=20,
)
def poll_task(self: CeleryTask, task_id: str) -> None:
    with SyncSessionLocal() as session:
        task = session.get(Task, uuid.UUID(task_id))
        if task is None or task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
            return
        if task.provider_job_id is None:
            return  # нечего опрашивать — submit ещё не завершился/провалился раньше

        adapter = get_adapter(task.stage)
        provider_job_id = task.provider_job_id
        poll_attempt = task.attempt_no
        task_stage = task.stage

    try:
        result: ProviderJobResult = asyncio.run(adapter.poll(provider_job_id))
    except TRANSIENT_ERRORS:
        # Celery-level autoretry_for обработает: poll_task не переводит Task ни в
        # какой промежуточный статус перед вызовом poll() (в отличие от process_task
        # с его SUBMITTING), так что повторная доставка того же poll_task безопасна.
        raise
    except Exception as exc:
        # P0, найдено при добавлении первого реального async job+poll адаптера
        # (RunwayAdapter): раньше исключение из adapter.poll() вообще не ловилось
        # здесь и утекало из Celery-задачи необработанным — Task навсегда оставался
        # в WAITING_PROVIDER (стаб-адаптеры никогда не доходили до этого пути,
        # так как их poll() никогда не вызывался — они завершаются синхронно в
        # submit()). Заворачиваем в тот же FAILED-путь, что и остальной пайплайн.
        result = ProviderJobResult(
            provider_job_id=provider_job_id,
            status=ProviderJobStatus.FAILED,
            error_code="POLL_ERROR",
            error_detail=str(exc),
        )

    if result.status in (ProviderJobStatus.QUEUED, ProviderJobStatus.PROCESSING):
        delay = result.retry_after_seconds or _exponential_backoff(poll_attempt)
        # Провайдер ещё работает — продлеваем TTL слота, иначе при генерации дольше
        # SLOT_TTL_SECONDS слот протух бы между poll'ами и впустил вторую задачу
        # сверх лимита. refresh только продлевает существующий слот (см. _REFRESH_SCRIPT).
        provider = _SEMAPHORE_PROVIDER_BY_STAGE.get(task_stage)
        if provider is not None:
            provider_semaphore.refresh_slot(provider=provider, holder=task_id)
        with SyncSessionLocal() as session:
            task = session.get(Task, uuid.UUID(task_id))
            task.next_poll_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            session.commit()
        poll_task.apply_async(args=[task_id], countdown=delay)
        return

    with SyncSessionLocal() as session:
        complete_task(session, task_id=uuid.UUID(task_id), result=result)
    # terminal у провайдера (completed/failed/retry) — слот отпускаем. При
    # retry_scheduled повторный process_task заберёт заново.
    _release_semaphore_if_held(task_stage, task_id)

    _maybe_retry_scheduled(self, task_id)


def _maybe_retry_scheduled(self: CeleryTask, task_id: str) -> None:
    """После complete_task проверяем: если domain-уровень запросил повтор
    (RETRY_SCHEDULED, провайдер вернул FAILED, но retry_count не исчерпан) —
    переставляем process_task с backoff."""
    with SyncSessionLocal() as session:
        task = session.get(Task, uuid.UUID(task_id))
        if task is not None and task.status == TaskStatus.RETRY_SCHEDULED:
            delay = _exponential_backoff(task.retry_count)
            process_task.apply_async(args=[task_id], countdown=delay)
