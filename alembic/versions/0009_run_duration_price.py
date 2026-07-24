"""run duration + deterministic price (pricing v3, no reserve)

Revision ID: 0009_run_duration_price
Revises: 0008_credit_transaction_note
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_run_duration_price"
down_revision: Union[str, None] = "0008_credit_transaction_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NON_TERMINAL_STATUSES = "('pending', 'submitting', 'waiting_provider', 'processing', 'retry_scheduled')"


def _fail_if_pipeline_not_drained() -> None:
    """P0 (ревью денежных путей): переход v2 (hold/settle) -> v3 (charge-on-success)
    небезопасен при незавершённых v2-ранах. У такого рана уже списаны HOLD'ы, а
    v3-код больше не делает settle/release, и финальный _charge_run выйдет по
    price=0 (legacy-раны не бэкфиллятся) — открытый HOLD навсегда, недооплата.
    Поэтому пайплайн обязан быть пуст: остановить worker/beat и дать ему опустеть
    перед миграцией. Проверка, а не строчка в README."""
    conn = op.get_bind()
    stuck = conn.execute(
        sa.text(f"SELECT count(*) FROM tasks WHERE status::text IN {NON_TERMINAL_STATUSES}")
    ).scalar_one()
    if stuck:
        raise RuntimeError(
            f"cannot switch to pricing v3: {stuck} tasks are still in flight. "
            "Stop worker/beat, wait for the pipeline to drain, then run the migration. "
            "See deploy/README.md."
        )


def upgrade() -> None:
    # Блокируем tasks на запись ДО drain-проверки: старый v2-API во время
    # `up --build` ещё жив и мог бы между count(*) и DDL создать новый v2-run
    # (INSERT в tasks с холдом в v2-схеме) — тогда drain-инвариант нарушится уже
    # после проверки, и после переключения на v3 останется открытый холд навсегда.
    # SHARE ROW EXCLUSIVE конфликтует с ROW EXCLUSIVE (INSERT/UPDATE tasks), но
    # пропускает чтения; ALTER generation_runs ниже берёт свой ACCESS EXCLUSIVE.
    # Тот же приём, что в 0007. Снимается автоматически на COMMIT миграции.
    op.execute("LOCK TABLE tasks IN SHARE ROW EXCLUSIVE MODE")

    _fail_if_pipeline_not_drained()
    # Цена ролика теперь детерминирована из выбранной длительности и списывается
    # один раз на успехе (без резерва). Не бэкфиллим legacy-раны: у них 0, они уже
    # завершены и оплачены по старой (hold/settle) схеме (drain-guard выше
    # гарантирует, что незавершённых v2-ранов нет).
    op.add_column("generation_runs", sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("generation_runs", sa.Column("price", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("generation_runs", "price")
    op.drop_column("generation_runs", "duration_seconds")
