import json
import logging
from datetime import datetime, timezone

from toontales_ai.observability.logging_config import (
    JSONFormatter,
    configure_logging,
    reset_request_id,
    set_request_id,
)


def _record(*, extra: dict | None = None, exc_info=None) -> logging.LogRecord:
    return logging.getLogger("toontales.test").makeRecord(
        "toontales.test",
        logging.INFO,
        __file__,
        1,
        "hello %s",
        ("world",),
        exc_info,
        extra=extra,
    )


def test_json_formatter_emits_required_fields_and_extra() -> None:
    payload = json.loads(JSONFormatter().format(_record(extra={"task_id": "task-1", "attempt": 2})))

    timestamp = datetime.fromisoformat(payload["timestamp"])
    assert timestamp.tzinfo == timezone.utc
    assert payload["level"] == "INFO"
    assert payload["logger"] == "toontales.test"
    assert payload["message"] == "hello world"
    assert payload["task_id"] == "task-1"
    assert payload["attempt"] == 2


def test_json_formatter_includes_request_id_only_when_set() -> None:
    without_request_id = json.loads(JSONFormatter().format(_record()))
    assert without_request_id.get("request_id") is None

    token = set_request_id("request-1")
    try:
        with_request_id = json.loads(JSONFormatter().format(_record()))
    finally:
        reset_request_id(token)

    assert with_request_id["request_id"] == "request-1"


def test_json_formatter_includes_exception() -> None:
    try:
        raise ValueError("invalid input")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    payload = json.loads(JSONFormatter().format(_record(exc_info=exc_info)))
    assert "ValueError: invalid input" in payload["exception"]


def test_configure_logging_is_idempotent() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    try:
        configure_logging()
        configure_logging()

        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0].formatter, JSONFormatter)
    finally:
        for handler in root_logger.handlers:
            if handler not in original_handlers:
                handler.close()
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
