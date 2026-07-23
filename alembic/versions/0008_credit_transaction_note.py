"""note on credit transactions (manual admin balance edits)

Revision ID: 0008_credit_transaction_note
Revises: 0007_spark_revaluation
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_credit_transaction_note"
down_revision: Union[str, None] = "0007_spark_revaluation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable: у автоматических проводок (hold/charge/release) причина очевидна
    # из task_id, заполнять её задним числом нечем и незачем.
    op.add_column("credit_transactions", sa.Column("note", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("credit_transactions", "note")
