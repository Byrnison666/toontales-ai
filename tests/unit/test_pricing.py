from decimal import Decimal

import pytest

from toontales_ai.config import settings as settings_module
from toontales_ai.orchestration.pricing import (
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    PRICE_ROUNDING_RUB,
    SPARK_PACKAGE_SIZES,
    clip_seconds_for,
    package_price_rub,
    price_from_duration,
    scene_count_for_duration,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def test_price_is_deterministic_and_known_before_start():
    # Ядро v3: цена детерминирована длительностью — одинакова при повторе.
    assert price_from_duration(30) == price_from_duration(30)
    assert price_from_duration(30) > 0


def test_price_grows_with_duration():
    assert price_from_duration(10) < price_from_duration(30) < price_from_duration(60)


def test_price_scales_roughly_linearly_with_duration():
    # Себестоимость доминируется посекундными стадиями, цена растёт почти линейно;
    # фикс раскадровки даёт небольшой сдвиг вверх на коротких.
    p10, p60 = price_from_duration(10), price_from_duration(60)
    assert p60 > p10
    assert p60 < 6 * p10  # не абсурдно дороже, чем 6× от 10с


def test_scene_count_keeps_clip_in_runway_range():
    for d in range(MIN_DURATION_SECONDS, MAX_DURATION_SECONDS + 1):
        n = scene_count_for_duration(d)
        clip = clip_seconds_for(d, n)
        assert n >= 1
        assert 2 <= clip <= 10, f"d={d}: clip {clip} вне диапазона Runway"


def test_scene_count_for_presets():
    assert scene_count_for_duration(10) == 2
    assert scene_count_for_duration(30) == 5
    assert scene_count_for_duration(60) == 10


def test_lipsync_adds_to_price(monkeypatch):
    monkeypatch.setenv("TOONTALES_LIPSYNC_ENABLED", "false")
    settings_module.get_settings.cache_clear()
    voiceover = price_from_duration(30)
    monkeypatch.setenv("TOONTALES_LIPSYNC_ENABLED", "true")
    settings_module.get_settings.cache_clear()
    with_lipsync = price_from_duration(30)
    assert with_lipsync > voiceover  # липсинк ~$0.045/с сверху


def test_spark_nominal_is_configurable(monkeypatch):
    base = price_from_duration(30)
    monkeypatch.setenv("TOONTALES_SPARK_COST_USD", "0.01")  # искра в 10× дороже
    settings_module.get_settings.cache_clear()
    cheaper = price_from_duration(30)
    assert cheaper < base  # дороже искра -> меньше искр за ту же себестоимость


# ---------- пакеты ----------


def test_package_sells_sparks_at_markup_over_cost():
    settings = settings_module.get_settings()
    for sparks in SPARK_PACKAGE_SIZES:
        cost_rub = Decimal(sparks) * settings.spark_cost_usd * settings.usd_rub_rate
        assert package_price_rub(sparks) / cost_rub >= settings.price_markup


def test_package_price_rounds_up_to_step():
    for sparks in SPARK_PACKAGE_SIZES:
        assert package_price_rub(sparks) % PRICE_ROUNDING_RUB == 0


def test_clip_distribution_sums_exactly_to_duration():
    """Дрейф недопустим: сумма клипов по сценам = ровно выбранная длительность,
    иначе видео короче оплаченного (недодача) или мы дарим лишние секунды."""
    from toontales_ai.orchestration.pricing import clip_seconds_for_scene

    for d in range(MIN_DURATION_SECONDS, MAX_DURATION_SECONDS + 1):
        n = scene_count_for_duration(d)
        clips = [clip_seconds_for_scene(d, n, i) for i in range(n)]
        assert sum(clips) == d, f"d={d}: сумма клипов {sum(clips)} != {d}"
        assert all(2 <= c <= 10 for c in clips)
