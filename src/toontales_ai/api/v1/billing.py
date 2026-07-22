"""Billing API: свой баланс/история (JWT) + admin-пополнение (admin-секрет).

Пополнение НЕ self-service: обычный пользователь по JWT видит только свой баланс
и историю, а начисление кредитов (POST /admin/topup) требует X-Admin-Key —
иначе любой юзер начеканил бы себе кредиты бесплатно. Реальный платёжный
провайдер (Stripe и т.п.) — отдельная задача поверх этого."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.api.deps import get_current_user_id, get_db_session, require_admin
from toontales_ai.orchestration import billing

router = APIRouter(prefix="/api/v1/billing")

MAX_TOPUP_AMOUNT = 1_000_000  # верхняя граница на одну операцию — защита от опечатки/переполнения


class BalanceResponse(BaseModel):
    user_id: uuid.UUID
    credit_balance: int


class TransactionItem(BaseModel):
    id: uuid.UUID
    type: str
    amount: int
    run_id: uuid.UUID | None
    task_id: uuid.UUID | None
    created_at: str


class TransactionsResponse(BaseModel):
    transactions: list[TransactionItem]


class AdminTopupRequest(BaseModel):
    user_id: uuid.UUID
    amount: int = Field(gt=0, le=MAX_TOPUP_AMOUNT)
    # Клиент задаёт ключ идемпотентности (напр. id платежа/заявки) — повтор с тем
    # же ключом не начислит дважды. Обязателен, чтобы ретрай не удвоил баланс.
    idempotency_key: str = Field(min_length=1, max_length=200)


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> BalanceResponse:
    balance = await billing.get_balance(session, user_id=user_id)
    return BalanceResponse(user_id=user_id, credit_balance=balance)


@router.get("/transactions", response_model=TransactionsResponse)
async def list_transactions(
    session: AsyncSession = Depends(get_db_session),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> TransactionsResponse:
    txs = await billing.list_transactions(session, user_id=user_id)
    return TransactionsResponse(
        transactions=[
            TransactionItem(
                id=t.id,
                type=t.type.value,
                amount=t.amount,
                run_id=t.run_id,
                task_id=t.task_id,
                created_at=t.created_at.isoformat(),
            )
            for t in txs
        ]
    )


@router.post("/admin/topup", response_model=BalanceResponse, dependencies=[Depends(require_admin)])
async def admin_topup(
    body: AdminTopupRequest,
    session: AsyncSession = Depends(get_db_session),
) -> BalanceResponse:
    try:
        new_balance = await billing.topup(
            session, user_id=body.user_id, amount=body.amount, idempotency_key=body.idempotency_key
        )
    except billing.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return BalanceResponse(user_id=body.user_id, credit_balance=new_balance)
