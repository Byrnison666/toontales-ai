import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from toontales_ai.domain.enums import (
    ConsistencyMethod,
    CreditTransactionType,
    MediaKind,
    OutboxStatus,
    ProviderJobStatus,
    RetentionClass,
    RunStatus,
    RunTrigger,
    Stage,
    TaskStatus,
)


def _pg_enum(enum_cls: type) -> Enum:
    """values_callable=member.value (не member.name): Postgres-типы в alembic-миграциях
    созданы со значениями "initial"/"pending"/... По умолчанию SQLAlchemy для
    Mapped[SomeEnum] без values_callable сериализует member.name ("INITIAL"), что
    не совпадает ни с одной меткой enum-типа в БД — INSERT падает с
    InvalidTextRepresentation на первой же реальной записи в любую enum-колонку."""
    return Enum(enum_cls, values_callable=lambda obj: [e.value for e in obj])


class Base(DeclarativeBase):
    type_annotation_map = {
        ConsistencyMethod: _pg_enum(ConsistencyMethod),
        RunTrigger: _pg_enum(RunTrigger),
        RunStatus: _pg_enum(RunStatus),
        Stage: _pg_enum(Stage),
        TaskStatus: _pg_enum(TaskStatus),
        ProviderJobStatus: _pg_enum(ProviderJobStatus),
        MediaKind: _pg_enum(MediaKind),
        RetentionClass: _pg_enum(RetentionClass),
        CreditTransactionType: _pg_enum(CreditTransactionType),
        OutboxStatus: _pg_enum(OutboxStatus),
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(unique=True, index=True)
    # nullable: существующие MVP-пользователи (созданы напрямую в БД до появления
    # auth) не имеют пароля и не могут логиниться — не ретроактивная миграция.
    password_hash: Mapped[str | None] = mapped_column(nullable=True)
    # Integer, минимальные единицы (центы кредита), не float — review.md §4.
    credit_balance: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (CheckConstraint("credit_balance >= 0", name="ck_users_balance_non_negative"),)


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    versions: Mapped[list["CharacterVersion"]] = relationship(back_populates="character")


class CharacterVersion(Base):
    """Неизменяем после использования в GenerationRun (review.md §8):
    приложение не должно допускать UPDATE версии, на которую уже есть FK-ссылка
    из GenerationRun.character_version_id."""

    __tablename__ = "character_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    character_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int]
    reference_assets: Mapped[dict] = mapped_column(JSONB, default=dict)
    prompt_template: Mapped[str]
    negative_prompt: Mapped[str] = mapped_column(default="")
    style_constraints: Mapped[dict] = mapped_column(JSONB, default=dict)
    consistency_method: Mapped[ConsistencyMethod]
    consistency_params: Mapped[dict] = mapped_column(JSONB, default=dict)
    wardrobe_tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    character: Mapped["Character"] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("character_id", "version_no", name="uq_character_version_no"),)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[RunTrigger] = mapped_column(default=RunTrigger.INITIAL)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[RunStatus] = mapped_column(default=RunStatus.PENDING)

    # Snapshot выбранной CharacterVersion на момент запуска (review.md §8) —
    # неизменяемость version + FK гарантируют, что run не "поедет" при новой версии персонажа.
    character_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("character_versions.id", ondelete="RESTRICT"), nullable=True
    )
    # Только non-secret fingerprint конфигурации провайдеров, не полный конфиг с credentials
    # (review.md §10: over-engineering / утечка секретов при полном snapshot).
    provider_config_fingerprint: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Предварительная смета и бюджетный потолок run (review.md §10, пробел "предварительная смета").
    estimated_cost: Mapped[int] = mapped_column(default=0)
    max_budget: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Scene(Base):
    """Привязан к GenerationRun, а не только к Project (review.md §3):
    новая раскадровка не должна переписывать исторический запуск."""

    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    generation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    scene_index: Mapped[int]
    script_text: Mapped[str]
    image_prompt: Mapped[str] = mapped_column(default="")
    camera_movement: Mapped[str] = mapped_column(default="")
    mood_notes: Mapped[str] = mapped_column(default="")
    scene_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (UniqueConstraint("generation_run_id", "scene_index", name="uq_run_scene_index"),)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[MediaKind]
    # Ключ объекта в object storage, не постоянный публичный URL (review.md §8) —
    # клиент получает short-lived presigned URL на чтение.
    storage_key: Mapped[str]
    content_type: Mapped[str]
    size_bytes: Mapped[int]
    checksum: Mapped[str]
    retention_class: Mapped[RetentionClass] = mapped_column(default=RetentionClass.EPHEMERAL)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), index=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    stage: Mapped[Stage]
    provider: Mapped[str]
    status: Mapped[TaskStatus] = mapped_column(default=TaskStatus.PENDING)

    # Номер технической попытки — отдельно от idempotency_key (review.md §1).
    attempt_no: Mapped[int] = mapped_column(default=0)
    retry_count: Mapped[int] = mapped_column(default=0)

    input_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    input_hash: Mapped[str]
    output_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    provider_job_id: Mapped[str | None] = mapped_column(nullable=True)
    provider_status: Mapped[ProviderJobStatus | None] = mapped_column(nullable=True)
    # celery_task_id — инфраструктурный идентификатор для диагностики,
    # не участвует в бизнес-инвариантах orchestration (review.md §10).
    celery_task_id: Mapped[str | None] = mapped_column(nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # cost — холд (верхняя граница, блокируется до запуска), price — фактическое
    # списание по real_cost_usd * наценка (orchestration/pricing.py). price=None,
    # пока задача не завершилась; разница cost - price возвращается на баланс.
    cost: Mapped[int] = mapped_column(default=0)
    price: Mapped[int | None] = mapped_column(nullable=True)
    # Себестоимость. Только для админки и сверки наценки — клиенту не отдаётся.
    real_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    # Стабильный ключ логической операции: hash(run_id + stage + scene_id + input_version).
    # attempt в ключ не входит (review.md §1).
    idempotency_key: Mapped[str] = mapped_column(unique=True, index=True)

    # Optimistic locking для конкурентных переходов статуса.
    version: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_tasks_run_stage_scene", "run_id", "stage", "scene_id"),
        Index("ix_tasks_next_poll_at", "next_poll_at"),
    )


class CreditTransaction(Base):
    """Append-only ledger. UNIQUE(idempotency_key) исключает повторное списание (review.md §4)."""

    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[CreditTransactionType]
    amount: Mapped[int]
    # Причина ручной правки баланса админом. Для автоматических проводок пусто:
    # у hold/charge/release причина очевидна из task_id. Ручное изменение чужих
    # денег без записанного основания — дыра в аудите.
    note: Mapped[str | None] = mapped_column(nullable=True)
    idempotency_key: Mapped[str] = mapped_column(unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PipelineOutbox(Base):
    """Единственное место, откуда что-либо реально уходит в Celery.
    Task+CreditTransaction+Outbox коммитятся в одной Postgres-транзакции;
    сама постановка в очередь происходит отдельным dispatcher-ом ПОСЛЕ commit
    (at-least-once, обработчики Celery обязаны быть идемпотентны)."""

    __tablename__ = "pipeline_outbox"

    id: Mapped[uuid.UUID] = _uuid_pk()
    event_type: Mapped[str] = mapped_column(default="enqueue_task")
    aggregate_id: Mapped[uuid.UUID]  # Task.id
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[OutboxStatus] = mapped_column(default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(server_default=func.now())
    lease_until: Mapped[datetime | None] = mapped_column(nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("event_type", "aggregate_id", name="uq_outbox_event_aggregate"),
        Index("ix_outbox_status_available_at", "status", "available_at"),
    )
