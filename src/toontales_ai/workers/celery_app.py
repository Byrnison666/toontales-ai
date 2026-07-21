from celery import Celery
from celery.signals import beat_init, task_postrun, task_prerun, worker_ready

from toontales_ai.config.settings import get_settings
from toontales_ai.observability.logging_config import configure_logging, set_request_id

configure_logging()

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
    # посреди обработки (review.md §7). ВАЖНО: правильное имя настройки —
    # task_reject_on_worker_lost (task_reject_on_lost, стоявшее здесь раньше,
    # Celery молча игнорировал как неизвестный ключ, оставляя эффективное
    # значение None — задача НЕ реджектилась/не переставлялась при потере
    # воркера; найдено admission-control-ревью).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=120,
    task_time_limit=180,
    task_default_retry_delay=10,
    # По умолчанию Celery при старте worker-процесса захватывает root logger и
    # переопределяет его handlers своими (P0, найдено security/observability-
    # ревью: наш configure_logging() выше вызывается на импорте модуля, но
    # worker_hijack_root_logger=True стирает это при фактическом запуске `celery
    # worker` — все domain-логи из pipeline_sync.py/beat.py уходили бы НЕ в JSON
    # и без request_id/task_id корреляции).
    worker_hijack_root_logger=False,
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


@task_prerun.connect
def _set_task_request_id(*, task_id: str | None = None, **_: object) -> None:
    set_request_id(str(task_id) if task_id is not None else None)


@task_postrun.connect
def _clear_task_request_id(**_: object) -> None:
    set_request_id(None)


def _start_metrics_server(**_: object) -> None:
    # Отдельный HTTP-сервер только для Prometheus scrape этого процесса
    # (worker/beat) — их prometheus_client.REGISTRY физически не тот же объект,
    # что у FastAPI-процесса с эндпоинтом /metrics на основном порту 8000
    # (security/observability-ревью: без этого TASK_TRANSITIONS_TOTAL и
    # RECONCILED_TASKS_TOTAL, инкрементируемые в pipeline_sync.py/beat.py,
    # никогда не попадали бы в Prometheus). Импорт внутри функции — на момент
    # импорта модуля celery_app.py (в т.ч. FastAPI-процессом через ленивый
    # локальный импорт в orchestration/outbox_dispatcher.py) сигнал ещё не
    # сработал, порт не занимается, если это не настоящий worker/beat процесс.
    from prometheus_client import start_http_server

    start_http_server(get_settings().metrics_port)


worker_ready.connect(_start_metrics_server)
beat_init.connect(_start_metrics_server)
