from decimal import Decimal

import pytest

from toontales_ai.domain.enums import Stage
from toontales_ai.orchestration.real_cost import compute_real_cost_usd


@pytest.mark.parametrize(
    ("stage", "usage", "expected"),
    [
        (
            # Sonnet 5: 1250×$3/1M + 320×$15/1M = 0.00375 + 0.0048 = 0.00855
            Stage.STORYBOARD,
            {"input_tokens": 1250, "output_tokens": 320},
            Decimal("0.008550"),
        ),
        (Stage.IMAGE, {"images": 3}, Decimal("0.150000")),
        (Stage.VIDEO, {"duration_seconds": 5}, Decimal("0.250000")),  # gen4_turbo 5 кред/с
        (Stage.AUDIO, {"characters": 1234}, Decimal("0.123400")),
        (Stage.LIPSYNC, {"duration_seconds": "5.5"}, Decimal("0.247500")),
        (Stage.COMPOSITION, None, Decimal("0.000000")),
    ],
)
def test_compute_real_cost_usd(stage, usage, expected):
    assert compute_real_cost_usd(stage, usage) == expected


def test_compute_real_cost_usd_returns_none_without_usage():
    assert compute_real_cost_usd(Stage.VIDEO, None) is None


def test_compute_real_cost_usd_returns_none_when_required_field_is_missing():
    assert compute_real_cost_usd(Stage.STORYBOARD, {"input_tokens": 100}) is None
