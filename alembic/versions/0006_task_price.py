"""task price in sparks (settle by actual cost)

Revision ID: 0006_task_price
Revises: 0005_credit_type_topup
Create Date: 2026-07-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_task_price"
down_revision: Union[str, None] = "0005_credit_type_topup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # nullable без backfill намеренно: у задач, завершённых до перехода на
    # списание по факту, фактической цены не существует — там списан весь холд.
    # NULL честно отражает "цена не считалась", 0 соврал бы, что было бесплатно.
    op.add_column("tasks", sa.Column("price", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "price")
