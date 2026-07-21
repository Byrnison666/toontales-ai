from prometheus_client import Counter, Histogram

# Allowlist кодов ошибок для label PROVIDER_ERRORS_TOTAL: часть error_code
# приходит сырой из ответа вендора (data.get("errorCode")/failureCode у Runway/
# Sync.so) — неограниченный набор значений в label взорвал бы cardinality
# Prometheus (security-ревью). Известные коды пропускаем как есть, всё
# остальное сворачиваем в "other". Наши собственные коды (NO_OUTPUT, REJECTED,
# CANCELLED, NO_VALID_ARTIFACT, COMPOSITION_FAILED, TASK_EXECUTION_ERROR,
# POLL_ERROR, INSUFFICIENT_CREDITS, RECONCILE_TIMEOUT) — стабильны и известны.
KNOWN_ERROR_CODES = frozenset(
    {
        "NO_OUTPUT",
        "REJECTED",
        "CANCELLED",
        "NO_VALID_ARTIFACT",
        "COMPOSITION_FAILED",
        "TASK_EXECUTION_ERROR",
        "POLL_ERROR",
        "INSUFFICIENT_CREDITS",
        "RECONCILE_TIMEOUT",
    }
)


def normalize_error_code(error_code: str | None) -> str:
    if error_code and error_code in KNOWN_ERROR_CODES:
        return error_code
    return "other"


HTTP_REQUESTS_TOTAL = Counter(
    "toontales_http_requests_total",
    "HTTP requests",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "toontales_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
)
TASK_TRANSITIONS_TOTAL = Counter(
    "toontales_task_transitions_total",
    "Task status transitions",
    ["stage", "status"],
)
TASK_REAL_COST_USD_TOTAL = Counter(
    "toontales_task_real_cost_usd_total",
    "Cumulative real USD cost of completed tasks",
    ["stage"],
)
PROVIDER_ERRORS_TOTAL = Counter(
    "toontales_provider_errors_total",
    "Provider adapter errors",
    ["stage", "error_code"],
)
RECONCILED_TASKS_TOTAL = Counter(
    "toontales_reconciled_tasks_total",
    "Tasks recovered by reconcile_stale_tasks",
    ["reconciliation_type"],
)
