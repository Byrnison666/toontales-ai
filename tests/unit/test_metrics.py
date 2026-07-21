from prometheus_client import Counter, Histogram

from toontales_ai.observability import metrics


def test_metrics_have_expected_types_and_labels() -> None:
    expected = {
        metrics.HTTP_REQUESTS_TOTAL: (Counter, ("method", "path", "status_code")),
        metrics.HTTP_REQUEST_DURATION_SECONDS: (Histogram, ("method", "path")),
        metrics.TASK_TRANSITIONS_TOTAL: (Counter, ("stage", "status")),
        metrics.TASK_REAL_COST_USD_TOTAL: (Counter, ("stage",)),
        metrics.PROVIDER_ERRORS_TOTAL: (Counter, ("stage", "error_code")),
        metrics.RECONCILED_TASKS_TOTAL: (Counter, ("reconciliation_type",)),
    }

    for metric, (metric_type, labelnames) in expected.items():
        assert isinstance(metric, metric_type)
        assert metric._labelnames == labelnames


def test_normalize_error_code_passes_known_and_collapses_unknown() -> None:
    assert metrics.normalize_error_code("NO_OUTPUT") == "NO_OUTPUT"
    assert metrics.normalize_error_code("INSUFFICIENT_CREDITS") == "INSUFFICIENT_CREDITS"
    # Сырые/произвольные коды вендора не должны плодить cardinality.
    assert metrics.normalize_error_code("some_random_runway_failure_code_12345") == "other"
    assert metrics.normalize_error_code(None) == "other"
    assert metrics.normalize_error_code("") == "other"
