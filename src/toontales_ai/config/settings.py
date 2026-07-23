from decimal import Decimal
from functools import lru_cache

from pydantic import Field, field_validator

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
    # Модель image-to-video — ТОЛЬКО gen4_turbo (5 кред/с = $0.05/с), см. валидатор
    # _only_turbo ниже. Тариф захардкожен в real_cost.py и STAGE_COST_USD_MAX;
    # gen4.5 (10 кред/с) при том же тарифе привёл бы к недосписанию вдвое, поэтому
    # запрещён на уровне настроек, а не оставлен на дисциплину.
    runway_video_model: str = "gen4_turbo"

    # Lipsync-стадия (Sync.so). True (default) — говорящие губы, видео фикс-длины,
    # звук вжигается в клип. False — voiceover-режим: озвучка кладётся поверх немого
    # видео на этапе composition, длина видео подгоняется под озвучку (Runway
    # duration = длине аудио, кламп 2..10с). Voiceover убирает стадию LIPSYNC из DAG
    # (VIDEO становится join на IMAGE+AUDIO) и зависимость от Sync.so — дешевле и без
    # concurrency-боттлнека. Меняет форму DAG (domain/enums.py) на старте процесса.
    lipsync_enabled: bool = True

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

    # Прайсинг. Искра — единица СЕБЕСТОИМОСТИ: списание с баланса идёт ровно по
    # затратам провайдерам (orchestration/real_cost.py), один в один, без наценки.
    # Наценка берётся один раз — в цене пакета искр (pricing.SPARK_PACKAGES).
    # Умножать на price_markup ещё и при списании нельзя: получится markup².
    #
    # gt=0 не косметика: spark_cost_usd=0 роняет settle делением на ноль уже
    # ПОСЛЕ оплаченной нами генерации, отрицательное значение создаёт
    # отрицательные холды и начисляет баланс при удержании. Отрицательный
    # markup/курс/буфер дают нулевую или отрицательную цену пакета.
    spark_cost_usd: Decimal = Field(default=Decimal("0.001"), gt=0)
    price_markup: Decimal = Field(default=Decimal("3"), gt=0)

    # Себестоимость номинирована в USD, а пакеты продаются за рубли, поэтому
    # движение курса съедает маржу. Курс фиксируем и закладываем буфер на его
    # рост; пересматривать вместе с тарифами провайдеров (см. real_cost.py).
    # Источник: ЦБ РФ, 2026-07-24.
    usd_rub_rate: Decimal = Field(default=Decimal("78.4049"), gt=0)
    # ge=0: буфер может быть нулевым (продавать по курсу без запаса), но не
    # отрицательным — иначе продаём дешевле курса.
    usd_rub_buffer: Decimal = Field(default=Decimal("0.15"), ge=0)

    @field_validator("runway_video_model")
    @classmethod
    def _only_turbo(cls, value: str) -> str:
        # real_cost.py и STAGE_COST_USD_MAX жёстко считают тариф gen4_turbo
        # (5 кредитов/с). gen4.5 стоит вдвое дороже — при нём мы системно
        # недосписывали бы вдвое, и метрика клампа не сработала бы (обе локальные
        # константы устарели одинаково). Видео только turbo — решение продукта.
        if value != "gen4_turbo":
            raise ValueError(
                f"runway_video_model must be 'gen4_turbo' (got {value!r}): "
                "real_cost/hold assume its tariff; gen4.5 would silently halve billing"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
