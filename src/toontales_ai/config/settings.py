from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TOONTALES_", extra="ignore")

    database_url: str = "postgresql+asyncpg://toontales:toontales@localhost:5432/toontales"
    test_database_url: str = "postgresql+psycopg://toontales:toontales@localhost:5432/toontales_test"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str | None = None
    s3_bucket: str = "toontales-media"
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    ephemeral_asset_ttl_days: int = 14

    ws_ticket_ttl_seconds: int = 60

    # Celery worker/beat — отдельные процессы от FastAPI (api имеет свой /metrics
    # на основном порту); каждый в своём контейнере поднимает мини HTTP-сервер
    # только для Prometheus scrape (prometheus_client.REGISTRY процесса не виден
    # снаружи иначе — найдено security/observability-ревью).
    metrics_port: int = 9100

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expires_minutes: int = 24 * 60

    # Секрет для admin-эндпоинтов (пополнение баланса). В MVP нет ролей/отдельной
    # admin-аутентификации — POST /billing/admin/topup защищён этим секретом в
    # заголовке X-Admin-Key, чтобы обычный юзер не начислял себе кредиты бесплатно.
    admin_api_key: str = ""

    # Стартовый бонус кредитов новому пользователю при регистрации.
    # По умолчанию 0: каждая генерация стоит реальных денег провайдерам (~$3.58/ролик),
    # а регистрация ничего не стоит — любой ненулевой бонус абузится мультиаккаунтами
    # (temp-mail/VPN обходят email-verify и IP-лимиты), раздавая живые деньги.
    # Единственный надёжный барьер — карта на файле (Stripe SetupIntent); до интеграции
    # платежей бонус выключен, а ценность сервиса демонстрируется обучающим роликом на
    # лендинге. Пополнение — только админом (POST /billing/admin/topup, X-Admin-Key).
    signup_bonus_credits: int = 0

    # fail-closed по умолчанию (review.md §10) — недоступность модератора блокирует контент.
    moderation_fail_open: bool = False

    rate_limit_generate_per_minute: int = 5

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    runway_api_key: str = ""

    sync_api_key: str = ""
    sync_model: str = "lipsync-2"
    # Лимит одновременных генераций Sync.so (тариф: hobbyist=1). Admission control
    # (orchestration/provider_semaphore.py) отсекает lipsync-запросы сверх лимита
    # ДО обращения к API, вместо ловли 429. При апгрейде тарифа — поднять здесь.
    sync_max_concurrency: int = 1

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    # Anthropic гео-блокирует РФ (403 "Request not allowed"). При деплое на
    # российском VPS storyboard-вызовы роутятся через прокси вне РФ (http(s):// или
    # socks5:// — для socks нужен httpx[socks]). Через Anthropic идёт только текст
    # сюжета, не ПДн, поэтому прокси не нарушает локализацию 152-ФЗ. Пусто = прямое
    # соединение (для окружений без гео-блока).
    anthropic_proxy_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
