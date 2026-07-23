"""Требует live PostgreSQL (skip, если недоступна) — см. conftest.py.
start_run() принимает AsyncSession — используем AsyncSessionLocal (тот же
паттерн, что test_auth_endpoints.py/test_partial_rerun_join_stages.py),
db_session (sync) только для сидинга/чтения после."""

import uuid

import pytest

from toontales_ai.domain.models import Project, User
from toontales_ai.orchestration.pipeline_async import MAX_ASSUMED_SCENES, InsufficientCreditsError, start_run
from toontales_ai.orchestration.pricing import estimate_run_cost, stage_hold
from toontales_ai.storage.db import AsyncSessionLocal


def _seed_user_and_project(session, *, credit_balance: int):
    user = User(email=f"{uuid.uuid4()}@example.com", credit_balance=credit_balance)
    session.add(user)
    session.flush()
    project = Project(user_id=user.id, name="p")
    session.add(project)
    session.flush()
    session.commit()
    return user, project


async def test_start_run_rejects_balance_sufficient_only_for_first_stage(db_session):
    """P0 (аудит финансовой корректности): раньше здесь проверялась только
    холд одной стадии STORYBOARD, а не полный холд run (max_budget) —
    пользователь с балансом между этими двумя цифрами мог СТАРТОВАТЬ
    run, который не сможет оплатить на 2-3 стадии (см. test_credit_and_
    duplicate_delivery.test_hold_and_enqueue_fails_task_explicitly_when_
    balance_insufficient для того, что происходит дальше)."""
    from toontales_ai.domain.enums import Stage

    storyboard_cost = stage_hold(Stage.STORYBOARD)
    max_budget = estimate_run_cost(MAX_ASSUMED_SCENES)
    assert storyboard_cost < max_budget  # sanity: сценарий вообще имеет смысл проверять

    user, project = _seed_user_and_project(db_session, credit_balance=storyboard_cost + 1)

    async with AsyncSessionLocal() as session:
        with pytest.raises(InsufficientCreditsError):
            await start_run(session, project_id=project.id, user_id=user.id, script_text="a story")


async def test_start_run_succeeds_with_full_budget(db_session):
    from toontales_ai.domain.enums import Stage

    max_budget = estimate_run_cost(MAX_ASSUMED_SCENES)
    user, project = _seed_user_and_project(db_session, credit_balance=max_budget)

    async with AsyncSessionLocal() as session:
        run = await start_run(session, project_id=project.id, user_id=user.id, script_text="a story")
        await session.commit()

    assert run.max_budget == max_budget

    db_session.refresh(user)
    assert user.credit_balance == max_budget - stage_hold(Stage.STORYBOARD)
