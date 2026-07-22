# Деплой ToonTales AI

Три сценария. Все читают конфиг из `.env` в корне проекта
(скопируйте `.env.example` → `.env` и заполните секреты).

- **Продакшн на VPS с доменом и HTTPS** — раздел 0 (Timeweb Cloud).
- **Локальный dev-стек в Docker** — раздел 1.
- **Нативный запуск через systemd** — раздел 2.

## 0. Продакшн на VPS (Timeweb Cloud, домен + HTTPS)

`docker-compose.prod.yml` — self-contained прод-стек: Caddy с авто-HTTPS
(Let's Encrypt) раздаёт собранный SPA и проксирует `/api` и `/ws` на FastAPI;
порты Postgres/Redis/API наружу не публикуются. Персональные данные граждан РФ
по 152-ФЗ должны храниться в РФ — поэтому VPS российский (Timeweb Cloud).

### Шаги

1. **VPS**: в панели Timeweb Cloud создайте облачный сервер (Ubuntu 24.04,
   минимум 2 vCPU / 4 ГБ RAM — FFmpeg и сборка фронтенда требуют памяти).
   Запишите публичный IP.
2. **Домен**: зарегистрируйте домен (можно в Timeweb). В DNS добавьте
   A-запись `@` (и при желании `www`) → публичный IP сервера. Дождитесь
   распространения DNS (`dig +short ваш-домен` должен вернуть IP).
3. **Docker** на сервере:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
4. **Код и секреты**:
   ```bash
   git clone https://github.com/Byrnison666/toontales-ai.git
   cd toontales-ai
   cp .env.example .env
   nano .env   # заполнить SITE_DOMAIN, ACME_EMAIL, POSTGRES_PASSWORD и все TOONTALES_* ключи
   ```
   Сгенерируйте сильные секреты: `openssl rand -hex 32` (JWT, admin-key,
   POSTGRES_PASSWORD).
5. **Порты**: в firewall Timeweb откройте 80 и 443 (и 22 для SSH). 80 нужен
   Let's Encrypt для выдачи сертификата.
6. **Запуск**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   docker compose -f docker-compose.prod.yml ps
   docker compose -f docker-compose.prod.yml logs -f caddy   # выдача TLS-сертификата
   ```
   Caddy автоматически получит HTTPS-сертификат при первом обращении к домену.
7. **Проверка**: откройте `https://ваш-домен` — должен открыться сайт;
   `https://ваш-домен/api/v1` доступен через прокси. Готово для отправки
   сайта на модерацию ЮKassa.

Обновление после `git pull`:
```bash
docker compose -f docker-compose.prod.yml up -d --build
```

> Админ-панель (`frontend/admin`) в прод-стек пока не входит — деплой на
> отдельный поддомен (`admin.домен`) добавляется отдельным шагом.

## 1. Docker Compose (локальный dev-стек)

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
