"""Себестоимость — только в админке. Клиент видит цену в искрах.

Регрессия: GET /runs/{id} раньше отдавал total_real_cost_usd и real_cost_usd по
каждой задаче, а фронт рисовал это на карточке ролика — то есть показывал
пользователю нашу закупочную цену.

Требует live PostgreSQL (skip, если недоступна) — см. conftest.py."""

import uuid

from toontales_ai.api.v1 import admin, runs
from toontales_ai.domain.enums import RunStatus, Stage, TaskStatus
from toontales_ai.domain.models import GenerationRun, Project, Task, User
from toontales_ai.orchestration.idempotency import task_idempotency_key
from toontales_ai.storage.db import AsyncSessionLocal

COST_USD_MARKER = "0.503591"  # сумма себестоимости заведённых задач


def _seed_completed_run(session) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=1000)
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()
    # Прайсинг v3: цена на уровне run; себестоимость (real_cost_usd) — на задачах,
    # только для админ-сверки, клиенту не отдаётся.
    run = GenerationRun(project_id=project.id, status=RunStatus.COMPLETED, duration_seconds=30, price=3170)
    session.add(run)
    session.flush()
    for stage, cost_usd in ((Stage.STORYBOARD, "0.003591"), (Stage.VIDEO, "0.500000")):
        key = task_idempotency_key(run_id=run.id, stage=stage, scene_id=None, input_version=str(uuid.uuid4()))
        session.add(
            Task(
                run_id=run.id, stage=stage, provider="x", status=TaskStatus.COMPLETED,
                input_hash=key, idempotency_key=key, real_cost_usd=cost_usd,
            )
        )
    session.commit()
    return user.id, run.id


async def test_run_snapshot_exposes_price_not_cost_price(db_session):
    user_id, run_id = _seed_completed_run(db_session)
    async with AsyncSessionLocal() as session:
        snapshot = await runs.get_run_snapshot(run_id=run_id, session=session, user_id=user_id)

    assert snapshot.price == 3170  # цена ролика в искрах, run-level
    assert snapshot.duration_seconds == 30

    # Ни одного USD-поля и ни одного значения себестоимости в сериализованном ответе.
    payload = snapshot.model_dump_json()
    assert "real_cost" not in payload
    assert "usd" not in payload.lower()
    assert COST_USD_MARKER not in payload


async def test_admin_still_sees_cost_price(db_session):
    """Обратная сторона: убирая себестоимость от клиента, нельзя потерять её в админке."""
    _, run_id = _seed_completed_run(db_session)
    async with AsyncSessionLocal() as session:
        detail = await admin.run_detail(run_id=run_id, session=session)

    assert detail.total_real_cost_usd is not None
    assert COST_USD_MARKER in detail.total_real_cost_usd


async def test_pricing_quote_returns_exact_prices_by_duration(db_session):
    """Прайсинг v3: котировка отдаёт точную цену по длительностям (пресеты + своя).
    Это финальная цена — резерва нет, столько и спишется на успехе."""
    from toontales_ai.orchestration.pricing import price_from_duration

    quote = await runs.pricing_quote(user_id=uuid.uuid4())
    by_duration = {item.duration_seconds: item.price for item in quote.prices}
    assert set(by_duration) == {10, 30, 60}
    for d, p in by_duration.items():
        assert p == price_from_duration(d)

    # своя длительность добавляется к пресетам
    quote_custom = await runs.pricing_quote(duration_seconds=45, user_id=uuid.uuid4())
    durations = {item.duration_seconds for item in quote_custom.prices}
    assert 45 in durations and {10, 30, 60} <= durations


async def test_package_prices_are_public_and_above_cost_price(db_session):
    """Прайс должен быть доступен без входа (оферта обещает его на странице
    оплаты) и при этом ни при каких настройках не опускаться ниже себестоимости."""
    from decimal import Decimal

    from toontales_ai.config.settings import get_settings

    settings = get_settings()
    response = await runs.pricing_packages()
    assert response.packages

    for item in response.packages:
        cost_rub = Decimal(item.sparks) * settings.spark_cost_usd * settings.usd_rub_rate
        assert Decimal(item.price_rub) / cost_rub >= settings.price_markup
    # Себестоимость в прайсе не светится — только искры и рубли.
    payload = response.model_dump_json()
    assert "usd" not in payload.lower()
