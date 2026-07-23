"""Billing API: свой баланс и история операций (JWT).

Пополнение НЕ self-service — иначе любой юзер начеканил бы себе искры бесплатно.
Ручная правка баланса живёт в админском роутере (POST /api/v1/admin/users/{id}/balance,
защищён X-Admin-Key), а автоматическое начисление после оплаты будет вызывать
billing.topup из вебхука платёжного провайдера."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.api.deps import get_current_user_id, get_db_session
from toontales_ai.orchestration import billing

router = APIRouter(prefix="/api/v1/billing")


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
