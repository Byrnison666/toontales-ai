"""credit transaction type topup

Revision ID: 0005_credit_type_topup
Revises: 0004_user_password_hash
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_credit_type_topup"
down_revision: Union[str, None] = "0004_user_password_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE нельзя выполнять внутри транзакционного блока в
    # старых PG; в PG 12+ допустимо, но не может выполняться совместно с другими
    # использованиями enum в той же транзакции. autocommit-блок — безопасный путь.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE credittransactiontype ADD VALUE IF NOT EXISTS 'topup'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значения из enum. Откат — no-op:
    # оставшееся значение 'topup' безвредно, если код его больше не использует.
    pass
