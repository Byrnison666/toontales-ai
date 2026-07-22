#!/usr/bin/env bash
# Ежедневный бэкап БД toontales: pg_dump из контейнера postgres, gzip,
# локальная копия (ротация 14 дней) + офсайт-копия в Cloudflare R2 (ротация 14 дней).
set -euo pipefail

BACKUP_DIR=/root/backups
PROJECT_DIR=/root/toontales-ai
COMPOSE="$PROJECT_DIR/docker-compose.prod.yml"
ENV_FILE="$PROJECT_DIR/.env"
R2_PREFIX=db-backups

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F_%H%M)
OUT="$BACKUP_DIR/toontales_${STAMP}.sql.gz"

# 1. Дамп БД из контейнера postgres.
cd "$PROJECT_DIR"
docker compose -f "$COMPOSE" exec -T postgres pg_dump -U toontales -d toontales | gzip > "$OUT"

# 2. Офсайт-копия в R2. Креды берём из .env приложения (те же R2-ключи).
val() { grep "^$1=" "$ENV_FILE" | cut -d= -f2-; }
BUCKET=$(val TOONTALES_S3_BUCKET)
export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=$(val TOONTALES_S3_ACCESS_KEY)
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$(val TOONTALES_S3_SECRET_KEY)
export RCLONE_CONFIG_R2_ENDPOINT=$(val TOONTALES_S3_ENDPOINT_URL)
export RCLONE_CONFIG_R2_REGION=auto
# R2-токен не имеет прав на CreateBucket — отключаем проверку/создание бакета,
# иначе rclone падает с 403 ещё до загрузки объекта.
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
rclone copy "$OUT" "R2:${BUCKET}/${R2_PREFIX}/"

# 3. Ротация: удалить старше 14 дней локально и в R2.
find "$BACKUP_DIR" -name 'toontales_*.sql.gz' -mtime +14 -delete
rclone delete "R2:${BUCKET}/${R2_PREFIX}/" --min-age 14d 2>/dev/null || true

echo "$(date -Is) backup ok: $OUT ($(du -h "$OUT" | cut -f1)) -> R2:${BUCKET}/${R2_PREFIX}/"
