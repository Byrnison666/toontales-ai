"""Billing: баланс, пополнение, история транзакций (async, FastAPI-сторона).

Пополнение (topup) в MVP — без реального платёжного провайдера: кредиты
начисляет админ (см. api/v1/billing.py, защита admin-секретом). CreditTransaction —
append-only ledger с UNIQUE(idempotency_key), поэтому topup идемпотентен:
повторный вызов с тем же ключом (ретрай сети, двойной клик) не начислит дважды.
Баланс меняется под SELECT ... FOR UPDATE — тот же паттерн, что hold/charge/release
в pipeline_sync/pipeline_async, чтобы конкурентные операции над одним user не
гонялись."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.domain.enums import CreditTransactionType
from toontales_ai.domain.models import CreditTransaction, User


class BillingError(Exception):
    pass


async def get_balance(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    balance = (
        await session.execute(select(User.credit_balance).where(User.id == user_id))
    ).scalar_one_or_none()
    if balance is None:
        raise BillingError(f"user {user_id} not found")
    return balance


async def topup(session: AsyncSession, *, user_id: uuid.UUID, amount: int, idempotency_key: str) -> int:
    """Начисляет amount кредитов пользователю. Идемпотентно по idempotency_key.
    Возвращает актуальный баланс после операции (или текущий, если это повтор)."""
    if amount <= 0:
        raise BillingError("topup amount must be positive")

    # FOR UPDATE до вставки: сериализует конкурентные topup/списания одного user.
    user = (
        await session.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise BillingError(f"user {user_id} not found")

    inserted_id = (
        await session.execute(
            pg_insert(CreditTransaction)
            .values(
                user_id=user_id,
                run_id=None,
                task_id=None,
                type=CreditTransactionType.TOPUP,
                amount=amount,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(CreditTransaction.id)
        )
    ).scalar_one_or_none()

    # Баланс инкрементируем ТОЛЬКО при реально вставленной транзакции (ON CONFLICT
    # DO NOTHING вернул None → это повтор с тем же ключом, начисление уже было).
    if inserted_id is not None:
        user.credit_balance += amount

    await session.commit()
    return user.credit_balance


async def admin_adjust_balance(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    mode: str,
    amount: int,
    note: str,
    idempotency_key: str,
) -> int:
    """Ручная правка баланса админом. mode="set" — установить точное значение,
    mode="delta" — начислить (amount > 0) или списать (amount < 0).

    Меняем баланс проводкой ADJUSTMENT, а не прямым UPDATE: ledger append-only и
    обязан сходиться с балансом, иначе сверка перестаёт что-либо значить.
    Идемпотентно по idempotency_key — повтор при ретрае сети не применится дважды.

    "set" по своей природе затирает конкурентную активность (списания, идущие
    прямо сейчас), поэтому берём FOR UPDATE и считаем дельту от значения под
    блокировкой, а не от того, что видел админ в браузере."""
    if mode not in ("set", "delta"):
        raise BillingError(f"unknown mode {mode!r}")
    if not note.strip():
        raise BillingError("note is required: manual balance edits must state a reason")

    user = (
        await session.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None:
        raise BillingError(f"user {user_id} not found")

    delta = amount - user.credit_balance if mode == "set" else amount
    if delta == 0:
        return user.credit_balance
    if user.credit_balance + delta < 0:
        raise BillingError(
            f"balance would go negative: {user.credit_balance} + {delta}"
        )

    inserted_id = (
        await session.execute(
            pg_insert(CreditTransaction)
            .values(
                user_id=user_id,
                run_id=None,
                task_id=None,
                type=CreditTransactionType.ADJUSTMENT,
                amount=delta,
                note=note.strip(),
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(CreditTransaction.id)
        )
    ).scalar_one_or_none()

    # Баланс двигаем ТОЛЬКО если проводка реально вставлена: None означает повтор
    # с тем же ключом, изменение уже применено.
    if inserted_id is not None:
        user.credit_balance += delta

    await session.commit()
    return user.credit_balance


async def list_transactions(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> Sequence[CreditTransaction]:
    return (
        await session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
