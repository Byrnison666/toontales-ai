from decimal import Decimal

import pytest

from toontales_ai.config import settings as settings_module
from toontales_ai.domain.enums import Stage
from toontales_ai.orchestration import real_cost
from toontales_ai.orchestration.pricing import (
    PRICE_ROUNDING_RUB,
    SPARK_PACKAGE_SIZES,
    STAGE_COST_USD_MAX,
    estimate_run_cost,
    package_price_rub,
    price_sparks,
    stage_hold,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def test_spark_is_a_unit_of_cost_price_not_of_revenue():
    # Ядро модели: искра = себестоимость. Списание один в один, без наценки —
    # иначе наценка возьмётся дважды (при продаже и при списании) и станет ×9.
    assert price_sparks(Decimal("1.00")) == 1000  # 1 / 0.001
    assert price_sparks(Decimal("0.001")) == 1


def test_price_rounds_up_never_down():
    # Округление вниз означало бы работу в убыток на копейку с каждой задачи.
    assert price_sparks(Decimal("0.0001")) == 1
    assert price_sparks(Decimal("0")) == 0


def test_price_scales_linearly_with_cost():
    assert price_sparks(Decimal("2.00")) == 2 * price_sparks(Decimal("1.00"))


def test_package_sells_sparks_at_markup_over_their_cost_price():
    """То, ради чего всё: пакет приносит втрое больше, чем стоят его искры."""
    settings = settings_module.get_settings()
    for sparks in SPARK_PACKAGE_SIZES:
        cost_rub = Decimal(sparks) * settings.spark_cost_usd * settings.usd_rub_rate
        price = package_price_rub(sparks)
        assert price / cost_rub >= settings.price_markup, f"{sparks}: наценка ниже заданной"


def test_package_price_rounds_up_never_below_floor():
    settings = settings_module.get_settings()
    floor = (
        Decimal(1_000) * settings.spark_cost_usd * settings.price_markup
        * settings.usd_rub_rate * (Decimal("1") + settings.usd_rub_buffer)
    )
    price = package_price_rub(1_000)
    assert price >= floor
    assert price % PRICE_ROUNDING_RUB == 0


def test_fx_buffer_protects_margin_when_rouble_falls(monkeypatch):
    """Буфер существует ровно для этого: курс уехал, а цена ещё старая."""
    settings = settings_module.get_settings()
    price = package_price_rub(10_000)
    weaker_rate = settings.usd_rub_rate * (Decimal("1") + settings.usd_rub_buffer)
    cost_rub_at_weaker_rate = Decimal(10_000) * settings.spark_cost_usd * weaker_rate
    assert price / cost_rub_at_weaker_rate >= settings.price_markup


def test_markup_and_nominal_are_configurable(monkeypatch):
    monkeypatch.setenv("TOONTALES_SPARK_COST_USD", "0.01")
    settings_module.get_settings.cache_clear()
    assert price_sparks(Decimal("1.00")) == 100


@pytest.mark.parametrize("stage", list(Stage))
def test_hold_covers_actual_cost_at_provider_limits(stage):
    """Холд обязан покрывать худший случай: если фактическая себестоимость
    превысит верхнюю границу, _settle зажмёт цену холдом и наценка просядет."""
    worst_case_usage = {
        Stage.STORYBOARD: {"input_tokens": 4000, "output_tokens": 4096},
        Stage.IMAGE: {"images": 1},
        Stage.VIDEO: {"duration_seconds": 10},  # MAX_DURATION_SECONDS у Runway
        Stage.AUDIO: {"characters": 1000},
        Stage.LIPSYNC: {"duration_seconds": 10},
        Stage.COMPOSITION: None,
    }[stage]
    actual = real_cost.compute_real_cost_usd(stage, worst_case_usage)
    assert actual is not None
    assert actual <= STAGE_COST_USD_MAX[stage], f"{stage}: холд {STAGE_COST_USD_MAX[stage]} < факт {actual}"


def test_typical_run_costs_less_than_hold():
    # Холд по верхней границе, списание по факту -> на типовой сцене (5 с видео,
    # ~200 символов озвучки) заметная часть холда возвращается клиенту.
    hold = estimate_run_cost(6)
    typical_usd = real_cost.compute_real_cost_usd(Stage.STORYBOARD, {"input_tokens": 1200, "output_tokens": 700})
    for _ in range(6):
        for stage, usage in (
            (Stage.IMAGE, {"images": 1}),
            (Stage.VIDEO, {"duration_seconds": 5}),
            (Stage.AUDIO, {"characters": 200}),
            (Stage.LIPSYNC, {"duration_seconds": 5}),
        ):
            typical_usd += real_cost.compute_real_cost_usd(stage, usage)
    assert price_sparks(typical_usd) < hold


def test_estimate_run_cost_grows_with_scene_count():
    assert estimate_run_cost(3) - estimate_run_cost(2) == estimate_run_cost(2) - estimate_run_cost(1)
    assert estimate_run_cost(0) == stage_hold(Stage.STORYBOARD) + stage_hold(Stage.COMPOSITION)


def test_voiceover_mode_drops_lipsync_from_hold(monkeypatch):
    monkeypatch.setenv("TOONTALES_LIPSYNC_ENABLED", "false")
    settings_module.get_settings.cache_clear()
    without_lipsync = estimate_run_cost(6)
    monkeypatch.setenv("TOONTALES_LIPSYNC_ENABLED", "true")
    settings_module.get_settings.cache_clear()
    with_lipsync = estimate_run_cost(6)
    assert with_lipsync - without_lipsync == 6 * stage_hold(Stage.LIPSYNC)


def test_audio_hold_covers_full_input_in_one_scene():
    """Верхняя граница AUDIO должна покрывать весь лимит ввода (4000 символов) в
    одной сцене: раскадровка не гарантирует распределения текста по сценам."""
    from toontales_ai.orchestration import real_cost

    # весь лимит script_text (schemas.GenerateProjectRequest.max_length) в одной сцене
    worst_case = real_cost.compute_real_cost_usd(Stage.AUDIO, {"characters": 4000})
    assert worst_case is not None
    assert worst_case <= STAGE_COST_USD_MAX[Stage.AUDIO], "AUDIO hold ниже худшего случая"
