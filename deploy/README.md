# Деплой ToonTales AI

Два способа запуска. Оба читают конфиг из `.env` в корне проекта
(скопируйте `.env.example` → `.env` и заполните секреты).

## 1. Docker Compose (рекомендуется — изолированный стек)

Поднимает api + worker + beat + собственные PostgreSQL и Redis. Миграции
накатываются автоматически one-shot сервисом `migrate` перед стартом приложения.

```bash
docker compose build
docker compose up -d
docker compose ps            # статусы + healthchecks
docker compose logs -f api   # структурированные JSON-логи
docker compose down          # остановить (данные Postgres в volume сохранятся)
```

Порты хоста:
- `8000` — FastAPI (`/healthz`, `/readyz`, `/metrics`, `/api/v1/*`)
- `9101` — Prometheus-метрики worker
- `9102` — Prometheus-метрики beat

`docker-compose.yml` переопределяет `TOONTALES_DATABASE_URL`/`TOONTALES_REDIS_URL`
на compose-хосты (`postgres`/`redis`) поверх `.env` — сам `.env` при этом остаётся
пригодным для нативного запуска (см. ниже), где эти URL указывают на `localhost`.

## 2. systemd (нативный, без Docker)

Для хостов с уже установленными PostgreSQL и Redis. Юниты в `deploy/systemd/`
рассчитаны на пути `/home/iorek/it/toontales-ai` и пользователя `iorek` —
поправьте под своё окружение.

```bash
sudo cp deploy/systemd/toontales-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now toontales-migrate toontales-api toontales-worker toontales-beat
sudo systemctl status toontales-api
journalctl -u toontales-worker -f   # JSON-логи через journald
```

worker и beat используют разные metrics-порты (9101/9102) через `Environment=`
override, т.к. на одном хосте (в отличие от отдельных контейнеров) не могут
делить один порт. worker запускается с `--pool=threads` — задачи I/O-bound,
threads-пул отдаёт Prometheus-метрики из задач в единый REGISTRY без
multiprocess-обвязки, которую потребовал бы prefork.
