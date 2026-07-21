FROM python:3.12-slim AS builder

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

RUN python -m venv /opt/venv

COPY pyproject.toml ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir .


FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    HOME="/home/appuser" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser --create-home appuser

WORKDIR /app

# Celery beat создаёт celerybeat-schedule в рабочем каталоге.
RUN chown appuser:appuser /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=appuser:appuser /build/src ./src
COPY --from=builder --chown=appuser:appuser /build/alembic ./alembic
COPY --from=builder --chown=appuser:appuser /build/alembic.ini ./alembic.ini
COPY --from=builder --chown=appuser:appuser /build/pyproject.toml ./pyproject.toml

USER appuser

EXPOSE 8000

CMD ["uvicorn", "toontales_ai.main:app", "--host", "0.0.0.0", "--port", "8000"]
