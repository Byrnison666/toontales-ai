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

### Выкатка прайсинга v2 (миграция `0007_spark_revaluation`)

Особый случай: миграция **необратимо пересчитывает балансы** пользователей под
новую шкалу искр и **отказывается запускаться, пока в пайплайне есть
незавершённые задачи** (незавершённая задача держит холд в старой шкале —
пересчёт свободного баланса без холдов развёл бы деньги с ledger). Обычный
`up -d --build` тут не годится: сервис `migrate` стартует, только `postgres`
готов, а старые `worker`/`beat` в это время ещё живы и могут менять баланс.

Порядок для перехода с прайсинга v1 на v2 (одноразовый, только на этой выкатке):

```bash
# 1. Бэкап и снимок «до»
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U toontales toontales | gzip > ~/backups/pre-pricing-v2-$(date +%F).sql.gz
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U toontales -d toontales -c "SELECT count(*) users, coalesce(sum(credit_balance),0) sparks FROM users"

# 2. Остановить приём и обработку, дать пайплайну опустеть
docker compose -f docker-compose.prod.yml stop worker beat
# Дождаться, пока не останется незавершённых задач (должно вернуть 0):
docker compose -f docker-compose.prod.yml exec -T postgres psql -U toontales -d toontales -tc \
  "SELECT count(*) FROM tasks WHERE status::text IN \
   ('pending','submitting','waiting_provider','processing','retry_scheduled')"

# 3. Обновить код и прогнать миграции (migrate дойдёт до 0007 и пересчитает балансы;
#    если задачи ещё в полёте — упадёт с понятной ошибкой, это защита, а не сбой)
git pull
docker compose -f docker-compose.prod.yml up -d --build

# 4. Проверка
docker compose -f docker-compose.prod.yml exec -T postgres psql -U toontales -d toontales \
  -c "SELECT version_num FROM alembic_version" \
  -c "SELECT coalesce(sum(credit_balance),0) FROM users"
curl -s https://<домен>/api/v1/pricing/packages
```

Ожидаемо: версия `0008_credit_transaction_note`, сумма искр выросла в ~1.949
раза (3275/1680), прайс отдаёт три пакета. Последующие выкатки — обычный
`up -d --build`; drain нужен только для 0007.

### Выкатка прайсинга v3 (миграция `0009_run_duration_price`)

Особый случай, как и 0007: переход с v2 (hold/settle — резерв на старте, доплата
по факту) на v3 (цена детерминирована длительностью, списывается один раз на
успехе, без резерва). v3-код больше не делает settle/release, поэтому
незавершённый v2-ран с уже списанным HOLD'ом при переключении остался бы с
открытым холдом навсегда — недооплата. Миграция 0009 содержит тот же drain-guard,
что и 0007: **отказывается запускаться, пока в пайплайне есть незавершённые
задачи**. Порядок — drain-first (одноразово, только на этой выкатке):

```bash
# 1. Бэкап и снимок «до» (балансы + открытые холды)
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U toontales toontales | gzip > ~/backups/pre-pricing-v3-$(date +%F).sql.gz

# 2. Остановить обработку, дать пайплайну опустеть (должно вернуть 0)
docker compose -f docker-compose.prod.yml stop worker beat
docker compose -f docker-compose.prod.yml exec -T postgres psql -U toontales -d toontales -tc \
  "SELECT count(*) FROM tasks WHERE status::text IN \
   ('pending','submitting','waiting_provider','processing','retry_scheduled')"

# 3. Обновить код и прогнать миграцию (migrate дойдёт до 0009; если задачи ещё
#    в полёте — упадёт с понятной ошибкой, это защита drain-guard, а не сбой)
git pull
docker compose -f docker-compose.prod.yml up -d --build

# 4. Проверка
docker compose -f docker-compose.prod.yml exec -T postgres psql -U toontales -d toontales \
  -c "SELECT version_num FROM alembic_version" \
  -c "\d generation_runs" | grep -E "duration_seconds|price"
```

Ожидаемо: версия `0009_run_duration_price`, у `generation_runs` появились колонки
`duration_seconds` и `price` (legacy-раны с 0 — они уже оплачены по v2). Последующие
выкатки — обычный `up -d --build`; drain нужен только для 0007 и 0009.

### Бэкапы БД

`deploy/scripts/toontales-backup.sh` делает `pg_dump` из контейнера postgres,
gzip и кладёт копию **локально** (`/root/backups`, ротация 14 дней) и **офсайт в
Cloudflare R2** (`<bucket>/db-backups/`, ротация 14 дней). R2-креды берёт из того
же `.env` (`TOONTALES_S3_*`); нужен установленный `rclone`.

Установка на сервере:
```bash
curl -fsSL https://rclone.org/install.sh | bash
sudo cp deploy/scripts/toontales-backup.sh /usr/local/bin/ && sudo chmod +x /usr/local/bin/toontales-backup.sh
/usr/local/bin/toontales-backup.sh          # разовый прогон/проверка
# ежедневно в 03:30:
( crontab -l 2>/dev/null; echo "30 3 * * * /usr/local/bin/toontales-backup.sh >> /root/backups/backup.log 2>&1" ) | crontab -
```

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

## 3. Мониторинг и алерты

Сервисы отдают метрики Prometheus: API — на `/metrics` основного порта,
worker и beat — на `metrics_port` (9100 внутри контейнера). **Prometheus входит
в прод-стек** (сервис `prometheus`, конфиг `deploy/monitoring/prometheus.yml`,
правила `deploy/monitoring/alerts.yml`) — поднимается вместе с остальными через
`up -d`. Скрейпит api/worker/beat внутри compose-сети.

UI/API Prometheus **не публикуется наружу** — порт на `127.0.0.1:9090`. Доступ с
рабочей машины через SSH-туннель:

```bash
ssh -L 9090:127.0.0.1:9090 toontales
# затем открыть http://localhost:9090 (вкладка Alerts — состояние правил)
```

Проверка правил перед выкаткой:

```bash
docker compose -f docker-compose.prod.yml exec prometheus \
  promtool check rules /etc/prometheus/alerts.yml
```

> Prometheus только вычисляет и показывает алерты в своём UI. Маршрутизация
> уведомлений (email/telegram) — отдельный компонент **Alertmanager**, в стек
> пока не входит. Firing-алерты видны на вкладке Alerts, но никуда не шлются.

### Зачем именно эти правила

Тарифы провайдеров захардкожены в `orchestration/real_cost.py`: себестоимость
не измеряется, а **считается**. Если Runway поднимет цену, наш расчёт не
изменится ни на цент — маржа просядет молча. Плюс прайсинг v3 не списывает на
старте, поэтому важны исходы роликов. Сигналы:

| Сигнал | Что означает |
|---|---|
| `RunChargeCappedByBalance` | списание за успешный ролик зажато балансом — недоплата (баланс просел мимо старт-проверки) |
| `RunFailureRateHigh` | много проваленных роликов — провайдерские расходы без выручки (сбой или абуз) |
| `TariffReviewOverdue` | тариф давно не сверяли руками с прайс-листом |
| `ProviderErrorRateHigh` | всплеск ошибок провайдера на стадии |
| `GET /api/v1/admin/provider-spend` | расчётный расход по провайдерам — сверять с инвойсом |

Автоматические — первые четыре, последний требует человека: только инвойс
показывает реальные деньги.
