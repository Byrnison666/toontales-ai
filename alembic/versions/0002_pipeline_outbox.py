"""pipeline outbox

Revision ID: 0002_pipeline_outbox
Revises: 0001_initial_schema
Create Date: 2026-07-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_pipeline_outbox"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

outbox_status_enum = postgresql.ENUM("pending", "publishing", "published", name="outboxstatus")


def upgrade() -> None:
    bind = op.get_bind()
    outbox_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "pipeline_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False, server_default="enqueue_task"),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", outbox_status_enum, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("event_type", "aggregate_id", name="uq_outbox_event_aggregate"),
    )
    op.create_index("ix_outbox_status_available_at", "pipeline_outbox", ["status", "available_at"])


def downgrade() -> None:
    op.drop_table("pipeline_outbox")
    bind = op.get_bind()
    outbox_status_enum.drop(bind, checkfirst=True)
