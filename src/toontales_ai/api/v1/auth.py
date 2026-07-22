"""Регистрация и логин — заменяет прежний способ заводить пользователей
напрямую в БД. Rate limiting на login (защита от credential stuffing/brute
force) здесь не реализован — существующий api/rate_limit.py ключуется по
user_id, которого до аутентификации ещё нет; per-IP лимит на auth-эндпоинты —
отдельная задача (review.md §10 стиль gap), не входит в этот шаг.

Security-ревью (независимый прогон, подтверждено измерением на этой машине):
1) Argon2 hash()/verify() — синхронные CPU/memory-hard вызовы, ~50мс каждый;
   вызов их напрямую из async-хендлера блокирует ВЕСЬ event loop процесса на
   это время — параллельный поток auth-запросов был бы DoS для всего API, не
   только для auth. Обёрнуты в asyncio.to_thread.
2) Неизвестный email или password_hash=NULL раньше пропускали verify_password
   целиком (0мс) против ~50мс для существующего аккаунта с неверным паролем —
   статистически различимый timing-канал для user enumeration по email.
   DUMMY_PASSWORD_HASH считается один раз при импорте модуля и используется
   для verify() на обеих "быстрых" ветках, чтобы время не отличалось."""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from toontales_ai.api.deps import get_db_session
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import CreditTransactionType
from toontales_ai.domain.models import CreditTransaction, User
from toontales_ai.security.auth import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth")

# OWASP-минимум для длины пароля; верхняя граница — защита от DoS через
# дорогое Argon2-хеширование сверхдлинного пароля.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256

# Используется для выравнивания времени ответа login() на "неизвестный email"/
# "пользователь без пароля" веток с веткой "известный email, неверный пароль" —
# сам пароль-заглушка никогда никому не сообщается и ни с чем не сравнивается.
DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-login")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class AuthResponse(BaseModel):
    user_id: uuid.UUID
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_db_session)) -> AuthResponse:
    password_hash = await asyncio.to_thread(hash_password, body.password)
    bonus = get_settings().signup_bonus_credits
    user = User(email=body.email, password_hash=password_hash, credit_balance=max(0, bonus))
    session.add(user)
    try:
        await session.flush()
        # Стартовый бонус фиксируем в append-only ledger (TOPUP) той же транзакцией,
        # что и создание юзера — иначе баланс "с неба" без следа в истории.
        if bonus > 0:
            session.add(
                CreditTransaction(
                    user_id=user.id,
                    run_id=None,
                    task_id=None,
                    type=CreditTransactionType.TOPUP,
                    amount=bonus,
                    idempotency_key=f"signup-bonus:{user.id}",
                )
            )
        await session.commit()
    except IntegrityError:
        # email UNIQUE — не подтверждаем существующему аккаунту факт занятости
        # email развёрнутой ошибкой; общий 409 без деталей.
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")

    return AuthResponse(user_id=user.id, access_token=create_access_token(user.id))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_db_session)) -> AuthResponse:
    user = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    # password_hash всегда DUMMY_PASSWORD_HASH на "быстрых" ветках (см. docstring
    # модуля) — verify_password вызывается в любом случае, время ответа не выдаёт
    # существование аккаунта.
    password_hash = user.password_hash if user is not None and user.password_hash else DUMMY_PASSWORD_HASH
    password_ok = await asyncio.to_thread(verify_password, body.password, password_hash)

    # Единая ошибка и для "нет такого email", и для "неверный пароль", и для
    # "пользователь создан до auth и password_hash=NULL" — не даём атакующему
    # через различие ответов узнать, зарегистрирован ли email (user enumeration).
    if user is None or user.password_hash is None or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")

    return AuthResponse(user_id=user.id, access_token=create_access_token(user.id))
