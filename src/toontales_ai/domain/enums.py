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
# Partial rerun выбранного stage обязан пересчитать весь набор ниже по цепочке (review.md §3).
STAGE_DOWNSTREAM: dict[Stage, tuple[Stage, ...]] = {
    Stage.STORYBOARD: (Stage.IMAGE, Stage.VIDEO, Stage.AUDIO, Stage.LIPSYNC, Stage.COMPOSITION),
    Stage.IMAGE: (Stage.VIDEO, Stage.LIPSYNC, Stage.COMPOSITION),
    Stage.VIDEO: (Stage.LIPSYNC, Stage.COMPOSITION),
    Stage.AUDIO: (Stage.LIPSYNC, Stage.COMPOSITION),
    Stage.LIPSYNC: (Stage.COMPOSITION,),
    Stage.COMPOSITION: (),
}

# Непосредственно следующие стадии при прогрессии пайплайна (в отличие от STAGE_DOWNSTREAM,
# который даёт полное транзитивное замыкание для инвалидации при partial rerun).
STAGE_IMMEDIATE_NEXT: dict[Stage, tuple[Stage, ...]] = {
    Stage.STORYBOARD: (Stage.IMAGE, Stage.AUDIO),
    Stage.IMAGE: (Stage.VIDEO,),
    Stage.VIDEO: (Stage.LIPSYNC,),
    Stage.AUDIO: (Stage.LIPSYNC,),
    Stage.LIPSYNC: (Stage.COMPOSITION,),
    Stage.COMPOSITION: (),
}

# Непосредственные предшественники для join-стадий: стадия создаётся только когда
# ВСЕ предшествующие стадии для той же сцены (video зависит только от image) завершены.
STAGE_PREDECESSORS: dict[Stage, tuple[Stage, ...]] = {
    Stage.IMAGE: (Stage.STORYBOARD,),
    Stage.AUDIO: (Stage.STORYBOARD,),
    Stage.VIDEO: (Stage.IMAGE,),
    Stage.LIPSYNC: (Stage.VIDEO, Stage.AUDIO),
    Stage.COMPOSITION: (Stage.LIPSYNC,),
}

# Стадии, привязанные к конкретной сцене, а не ко всему run.
SCENE_SCOPED_STAGES: frozenset[Stage] = frozenset(
    {Stage.IMAGE, Stage.VIDEO, Stage.AUDIO, Stage.LIPSYNC}
)


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


class OutboxStatus(str, enum.Enum):
    """Transactional outbox (review.md §10, пробел 'нет outbox/reconciler'):
    коммит Task+CreditTransaction и постановка в Celery разнесены во времени,
    outbox — единственный источник истины о том, что нужно доставить."""

    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
