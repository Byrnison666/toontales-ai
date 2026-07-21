import logging
import time
from uuid import uuid4

import redis.asyncio as redis
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from toontales_ai.config.settings import get_settings
from toontales_ai.observability import metrics
from toontales_ai.observability.logging_config import configure_logging, reset_request_id, set_request_id
from toontales_ai.storage import db as storage_db

configure_logging()

logger = logging.getLogger(__name__)

from toontales_ai.api.v1.auth import router as auth_router
from toontales_ai.api.v1.runs import router as runs_router
from toontales_ai.api.v1.ws import router as ws_router

settings = get_settings()
app = FastAPI(title="ToonTales AI")

app.include_router(auth_router)
app.include_router(runs_router)
app.include_router(ws_router)


@app.middleware("http")
async def generate_request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    token = set_request_id(request_id)
    started_at = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration = time.perf_counter() - started_at
        # route.path — ШАБЛОН пути (напр. "/api/v1/runs/{run_id}"), не сырой
        # request.url.path с подставленным UUID (security-ревью: сырой path
        # создавал бы неограниченное число Prometheus time series — по одному
        # на каждый уникальный run_id/user_id, включая 404 от сканеров —
        # unbounded cardinality = рост памяти без предела). Starlette
        # устанавливает scope["route"] только ПОСЛЕ успешного роутинга внутри
        # call_next; если маршрут не найден (404) — используем плоский label.
        route = request.scope.get("route")
        path_label = route.path if route is not None else "unmatched"
        try:
            metrics.HTTP_REQUESTS_TOTAL.labels(
                method=request.method,
                path=path_label,
                status_code=str(status_code),
            ).inc()
            metrics.HTTP_REQUEST_DURATION_SECONDS.labels(
                method=request.method,
                path=path_label,
            ).observe(duration)
        finally:
            reset_request_id(token)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/readyz")
async def readyz() -> JSONResponse:
    checks: dict[str, str] = {}

    # str(exc) НЕ уходит в HTTP-ответ (security-ревью): исключения драйверов
    # (asyncpg/redis) могут содержать хост/порт/имя базы/пользователя — полезная
    # для атакующего infra-recon информация неаутентифицированному клиенту.
    # Полная ошибка — только в лог, наружу — общий статус.
    try:
        async with storage_db.AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.error("readyz: database check failed", exc_info=True)
        checks["database"] = "unavailable"

    try:
        async with redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        ) as redis_client:
            await redis_client.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.error("readyz: redis check failed", exc_info=True)
        checks["redis"] = "unavailable"

    is_ready = all(result == "ok" for result in checks.values())
    return JSONResponse(
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=200 if is_ready else 503,
    )
