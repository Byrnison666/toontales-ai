"""real task cost

Revision ID: 0003_real_cost
Revises: 0002_pipeline_outbox
Create Date: 2026-07-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_real_cost"
down_revision: Union[str, None] = "0002_pipeline_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("real_cost_usd", sa.Numeric(18, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "real_cost_usd")
