import enum


class ConsistencyMethod(str, enum.Enum):
    REFERENCE_IMAGE = "reference_image"
    LORA = "lora"
    SEED = "seed"


class RunTrigger(str, enum.Enum):
    INITIAL = "initial"
    PARTIAL_RERUN = "partial_rerun"


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class Stage(str, enum.Enum):
    STORYBOARD = "storyboard_generation"
    IMAGE = "image_generation"
    VIDEO = "video_generation"
    AUDIO = "audio_generation"
    LIPSYNC = "lipsync"
    COMPOSITION = "composition"


# DAG зависимостей стадий (review.md §10: статическая таблица вместо generic DAG-engine).
# Форма зависит от settings.lipsync_enabled и фиксируется на старте процесса:
#   lipsync=True  — STORYBOARD→IMAGE,AUDIO; IMAGE→VIDEO; VIDEO+AUDIO→LIPSYNC; LIPSYNC→COMPOSITION
#   lipsync=False — STORYBOARD→IMAGE,AUDIO; IMAGE+AUDIO→VIDEO (join); VIDEO→COMPOSITION (voiceover)
# STAGE_DOWNSTREAM — полное транзитивное замыкание вниз (инвалидация при partial rerun,
# review.md §3). STAGE_IMMEDIATE_NEXT — непосредственная прогрессия. STAGE_PREDECESSORS —
# join-предшественники (стадия создаётся, когда ВСЕ предшественники завершены).
def _build_stage_graph(*, lipsync_enabled: bool):
    if lipsync_enabled:
        downstream = {
            Stage.STORYBOARD: (Stage.IMAGE, Stage.VIDEO, Stage.AUDIO, Stage.LIPSYNC, Stage.COMPOSITION),
            Stage.IMAGE: (Stage.VIDEO, Stage.LIPSYNC, Stage.COMPOSITION),
            Stage.VIDEO: (Stage.LIPSYNC, Stage.COMPOSITION),
            Stage.AUDIO: (Stage.LIPSYNC, Stage.COMPOSITION),
            Stage.LIPSYNC: (Stage.COMPOSITION,),
            Stage.COMPOSITION: (),
        }
        immediate_next = {
            Stage.STORYBOARD: (Stage.IMAGE, Stage.AUDIO),
            Stage.IMAGE: (Stage.VIDEO,),
            Stage.VIDEO: (Stage.LIPSYNC,),
            Stage.AUDIO: (Stage.LIPSYNC,),
            Stage.LIPSYNC: (Stage.COMPOSITION,),
            Stage.COMPOSITION: (),
        }
        predecessors = {
            Stage.IMAGE: (Stage.STORYBOARD,),
            Stage.AUDIO: (Stage.STORYBOARD,),
            Stage.VIDEO: (Stage.IMAGE,),
            Stage.LIPSYNC: (Stage.VIDEO, Stage.AUDIO),
            Stage.COMPOSITION: (Stage.LIPSYNC,),
        }
        scene_scoped = frozenset({Stage.IMAGE, Stage.VIDEO, Stage.AUDIO, Stage.LIPSYNC})
        # Линейный (топологический) порядок реально выполняемых этапов — для
        # отображения прогресса пользователю и расчёта процента по всему ролику.
        active = (Stage.STORYBOARD, Stage.IMAGE, Stage.VIDEO, Stage.AUDIO, Stage.LIPSYNC, Stage.COMPOSITION)
    else:
        # Voiceover: LIPSYNC исключён, VIDEO — join на (IMAGE, AUDIO) (нужна длина
        # озвучки для duration видео), COMPOSITION зависит от VIDEO.
        downstream = {
            Stage.STORYBOARD: (Stage.IMAGE, Stage.AUDIO, Stage.VIDEO, Stage.COMPOSITION),
            Stage.IMAGE: (Stage.VIDEO, Stage.COMPOSITION),
            Stage.AUDIO: (Stage.VIDEO, Stage.COMPOSITION),
            Stage.VIDEO: (Stage.COMPOSITION,),
            Stage.COMPOSITION: (),
        }
        immediate_next = {
            Stage.STORYBOARD: (Stage.IMAGE, Stage.AUDIO),
            Stage.IMAGE: (Stage.VIDEO,),
            Stage.AUDIO: (Stage.VIDEO,),
            Stage.VIDEO: (Stage.COMPOSITION,),
            Stage.COMPOSITION: (),
        }
        predecessors = {
            Stage.IMAGE: (Stage.STORYBOARD,),
            Stage.AUDIO: (Stage.STORYBOARD,),
            Stage.VIDEO: (Stage.IMAGE, Stage.AUDIO),
            Stage.COMPOSITION: (Stage.VIDEO,),
        }
        scene_scoped = frozenset({Stage.IMAGE, Stage.VIDEO, Stage.AUDIO})
        # Voiceover: LIPSYNC нет; озвучка (AUDIO) идёт до VIDEO, т.к. VIDEO join'ит
        # (IMAGE, AUDIO) — длина видео берётся из длины озвучки. Порядок «по факту».
        active = (Stage.STORYBOARD, Stage.IMAGE, Stage.AUDIO, Stage.VIDEO, Stage.COMPOSITION)
    return downstream, immediate_next, predecessors, scene_scoped, active


from toontales_ai.config.settings import get_settings  # noqa: E402  (после Stage для _build_stage_graph)

(
    STAGE_DOWNSTREAM,
    STAGE_IMMEDIATE_NEXT,
    STAGE_PREDECESSORS,
    SCENE_SCOPED_STAGES,
    ACTIVE_STAGES,
) = _build_stage_graph(lipsync_enabled=get_settings().lipsync_enabled)


class TaskStatus(str, enum.Enum):
    """Расширенная state machine из review.md §5: различает отправку,
    ожидание внешнего провайдера и локальную обработку."""

    PENDING = "pending"
    SUBMITTING = "submitting"
    WAITING_PROVIDER = "waiting_provider"
    PROCESSING = "processing"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TASK_TRANSITIONS: dict[TaskStatus, tuple[TaskStatus, ...]] = {
    TaskStatus.PENDING: (TaskStatus.SUBMITTING, TaskStatus.CANCELED),
    TaskStatus.SUBMITTING: (TaskStatus.WAITING_PROVIDER, TaskStatus.PROCESSING, TaskStatus.RETRY_SCHEDULED, TaskStatus.FAILED, TaskStatus.CANCELED),
    TaskStatus.WAITING_PROVIDER: (TaskStatus.PROCESSING, TaskStatus.COMPLETED, TaskStatus.RETRY_SCHEDULED, TaskStatus.FAILED, TaskStatus.CANCELED),
    TaskStatus.PROCESSING: (TaskStatus.COMPLETED, TaskStatus.RETRY_SCHEDULED, TaskStatus.FAILED, TaskStatus.CANCELED),
    TaskStatus.RETRY_SCHEDULED: (TaskStatus.SUBMITTING, TaskStatus.FAILED, TaskStatus.CANCELED),
    TaskStatus.COMPLETED: (),
    TaskStatus.FAILED: (),
    TaskStatus.CANCELED: (),
}


class ProviderJobStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class MediaKind(str, enum.Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    SUBTITLES = "subtitles"
    STORYBOARD = "storyboard"
    FINAL_RENDER = "final_render"


class RetentionClass(str, enum.Enum):
    EPHEMERAL = "ephemeral"  # TTL lifecycle policy (например, 14 дней)
    PERMANENT = "permanent"  # финальные рендеры


class CreditTransactionType(str, enum.Enum):
    HOLD = "hold"
    CHARGE = "charge"
    RELEASE = "release"
    ADJUSTMENT = "adjustment"
    TOPUP = "topup"  # пополнение баланса (billing); в MVP — только через admin-секрет


class OutboxStatus(str, enum.Enum):
    """Transactional outbox (review.md §10, пробел 'нет outbox/reconciler'):
    коммит Task+CreditTransaction и постановка в Celery разнесены во времени,
    outbox — единственный источник истины о том, что нужно доставить."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
