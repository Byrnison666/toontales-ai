"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

consistency_method_enum = postgresql.ENUM(
    "reference_image", "lora", "seed", name="consistencymethod"
)
run_trigger_enum = postgresql.ENUM("initial", "partial_rerun", name="runtrigger")
run_status_enum = postgresql.ENUM(
    "pending", "running", "completed", "failed", "canceled", name="runstatus"
)
stage_enum = postgresql.ENUM(
    "storyboard_generation",
    "image_generation",
    "video_generation",
    "audio_generation",
    "lipsync",
    "composition",
    name="stage",
)
task_status_enum = postgresql.ENUM(
    "pending",
    "submitting",
    "waiting_provider",
    "processing",
    "retry_scheduled",
    "completed",
    "failed",
    "canceled",
    name="taskstatus",
)
provider_job_status_enum = postgresql.ENUM(
    "queued", "processing", "succeeded", "failed", "canceled", name="providerjobstatus"
)
media_kind_enum = postgresql.ENUM(
    "image", "audio", "video", "subtitles", "storyboard", "final_render", name="mediakind"
)
retention_class_enum = postgresql.ENUM("ephemeral", "permanent", name="retentionclass")
credit_transaction_type_enum = postgresql.ENUM(
    "hold", "charge", "release", "adjustment", name="credittransactiontype"
)


def upgrade() -> None:
    bind = op.get_bind()
    for e in (
        consistency_method_enum,
        run_trigger_enum,
        run_status_enum,
        stage_enum,
        task_status_enum,
        provider_job_status_enum,
        media_kind_enum,
        retention_class_enum,
        credit_transaction_type_enum,
    ):
        e.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("credit_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("credit_balance >= 0", name="ck_users_balance_non_negative"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "characters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_characters_user_id", "characters", ["user_id"])

    op.create_table(
        "character_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("reference_assets", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("prompt_template", sa.String(), nullable=False),
        sa.Column("negative_prompt", sa.String(), nullable=False, server_default=""),
        sa.Column("style_constraints", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("consistency_method", consistency_method_enum, nullable=False),
        sa.Column("consistency_params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("wardrobe_tags", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("character_id", "version_no", name="uq_character_version_no"),
    )
    op.create_index("ix_character_versions_character_id", "character_versions", ["character_id"])

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    op.create_table(
        "generation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger", run_trigger_enum, nullable=False, server_default="initial"),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", run_status_enum, nullable=False, server_default="pending"),
        sa.Column("character_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("character_versions.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("provider_config_fingerprint", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("estimated_cost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_budget", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_generation_runs_project_id", "generation_runs", ["project_id"])

    op.create_table(
        "scenes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("generation_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_index", sa.Integer(), nullable=False),
        sa.Column("script_text", sa.String(), nullable=False),
        sa.Column("image_prompt", sa.String(), nullable=False, server_default=""),
        sa.Column("camera_movement", sa.String(), nullable=False, server_default=""),
        sa.Column("mood_notes", sa.String(), nullable=False, server_default=""),
        sa.Column("scene_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("generation_run_id", "scene_index", name="uq_run_scene_index"),
    )
    op.create_index("ix_scenes_generation_run_id", "scenes", ["generation_run_id"])

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stage", stage_enum, nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", task_status_enum, nullable=False, server_default="pending"),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("input_hash", sa.String(), nullable=False),
        sa.Column("output_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("error_payload", postgresql.JSONB(), nullable=True),
        sa.Column("provider_job_id", sa.String(), nullable=True),
        sa.Column("provider_status", provider_job_status_enum, nullable=True),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(), nullable=True),
        sa.Column("cost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_tasks_idempotency_key"),
    )
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])
    op.create_index("ix_tasks_idempotency_key", "tasks", ["idempotency_key"])
    op.create_index("ix_tasks_run_stage_scene", "tasks", ["run_id", "stage", "scene_id"])
    op.create_index("ix_tasks_next_poll_at", "tasks", ["next_poll_at"])

    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scene_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", media_kind_enum, nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(), nullable=False),
        sa.Column("retention_class", retention_class_enum, nullable=False, server_default="ephemeral"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_media_assets_run_id", "media_assets", ["run_id"])

    op.create_table(
        "credit_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", credit_transaction_type_enum, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_credit_transactions_idempotency_key"),
    )
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"])
    op.create_index("ix_credit_transactions_idempotency_key", "credit_transactions", ["idempotency_key"])


def downgrade() -> None:
    op.drop_table("credit_transactions")
    op.drop_table("media_assets")
    op.drop_table("tasks")
    op.drop_table("scenes")
    op.drop_table("generation_runs")
    op.drop_table("projects")
    op.drop_table("character_versions")
    op.drop_table("characters")
    op.drop_table("users")

    bind = op.get_bind()
    for e in (
        credit_transaction_type_enum,
        retention_class_enum,
        media_kind_enum,
        provider_job_status_enum,
        task_status_enum,
        stage_enum,
        run_status_enum,
        run_trigger_enum,
        consistency_method_enum,
    ):
        e.drop(bind, checkfirst=True)
