"""provider manual balance (Anthropic — остаток вводится вручную, нет API)

Revision ID: 0010_provider_manual_balance
Revises: 0009_run_duration_price
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_provider_manual_balance"
down_revision: Union[str, None] = "0009_run_duration_price"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Аддитивно (новая таблица) — drain не нужен.
    op.create_table(
        "provider_manual_balances",
        sa.Column("provider", sa.String(), primary_key=True),
        sa.Column("amount_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("set_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("provider_manual_balances")
