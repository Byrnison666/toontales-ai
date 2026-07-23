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


def upgrade() -> None:
    # Цена ролика теперь детерминирована из выбранной длительности и списывается
    # один раз на успехе (без резерва). Не бэкфиллим legacy-раны: у них 0, они уже
    # завершены и оплачены по старой (hold/settle) схеме.
    op.add_column("generation_runs", sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("generation_runs", sa.Column("price", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("generation_runs", "price")
    op.drop_column("generation_runs", "duration_seconds")
