from celery import Celery

from toontales_ai.config.settings import get_settings

_settings = get_settings()

celery_app = Celery("toontales_ai", broker=_settings.redis_url, backend=_settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Через Celery передаются только UUID/примитивы, не ORM-объекты (review.md §7).
    task_track_started=True,
    # acks_late + reject_on_worker_lost: сообщение не теряется при падении воркера
    # посреди обработки (review.md §7).
    task_acks_late=True,
    task_reject_on_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=120,
    task_time_limit=180,
    task_default_retry_delay=10,
)

celery_app.conf.beat_schedule = {
    "dispatch-outbox": {
        "task": "toontales_ai.workers.beat.dispatch_outbox",
        "schedule": 2.0,
    },
    "reconcile-stale-tasks": {
        "task": "toontales_ai.workers.beat.reconcile_stale_tasks",
        "schedule": 60.0,
    },
}

# autodiscover_tasks по конвенции ищет только модуль с именем "tasks" в каждом
# указанном пакете — workers/beat.py так никогда не подхватывался, и worker
# отклонял dispatch_outbox/reconcile_stale_tasks как "unregistered task" (P0,
# найдено при живом e2e-прогоне worker+beat: без dispatch_outbox ни одна задача,
# поставленная в PipelineOutbox через API, никогда не попадала бы в Celery).
celery_app.conf.imports = ("toontales_ai.workers.tasks", "toontales_ai.workers.beat")
celery_app.autodiscover_tasks(["toontales_ai.workers"])
