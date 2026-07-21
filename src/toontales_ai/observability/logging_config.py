"""Структурированное логирование приложения.

JSON нужен для агрегации логов в production: Loki, CloudWatch и аналогичные
системы ожидают машиночитаемые поля вместо разбора произвольного текста.
``request_id`` хранится в ``contextvars``, потому что контекст сохраняется через
``await`` и поддерживает изоляцию при переходах между asyncio task/thread
boundary, в отличие от обычной глобальной переменной. В Celery роль correlation
id выполняет ``task_id`` — см. ``workers/celery_app.py``.
"""

import json
import logging
import sys
import traceback
from contextvars import ContextVar, Token
from datetime import datetime, timezone


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_STANDARD_LOG_RECORD_ATTRIBUTES = frozenset(logging.makeLogRecord({}).__dict__)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(request_id: str | None) -> Token[str | None]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))

        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRIBUTES:
                payload.setdefault(key, value)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(*, level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
