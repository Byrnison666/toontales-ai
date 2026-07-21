"""user password hash

Revision ID: 0004_user_password_hash
Revises: 0003_real_cost
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_password_hash"
down_revision: Union[str, None] = "0003_real_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
