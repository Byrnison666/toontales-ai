"""Денежные настройки: валидация, защищающая маржу и списание.

Юнит-тесты, live-БД не нужна."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from toontales_ai.config.settings import Settings


def test_defaults_load():
    s = Settings()
    assert s.runway_video_model == "gen4_turbo"
    assert s.spark_cost_usd > 0


def test_video_model_locked_to_turbo():
    # gen4.5 стоит вдвое дороже при том же захардкоженном тарифе -> недосписание.
    with pytest.raises(ValidationError):
        Settings(runway_video_model="gen4.5")


@pytest.mark.parametrize("field", ["spark_cost_usd", "price_markup", "usd_rub_rate"])
def test_money_fields_reject_zero_and_negative(field):
    for bad in (Decimal("0"), Decimal("-1")):
        with pytest.raises(ValidationError):
            Settings(**{field: bad})


def test_fx_buffer_allows_zero_but_not_negative():
    Settings(usd_rub_buffer=Decimal("0"))  # продавать по курсу без запаса допустимо
    with pytest.raises(ValidationError):
        Settings(usd_rub_buffer=Decimal("-0.01"))
