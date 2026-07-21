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

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expires_minutes: int = 24 * 60

    # fail-closed по умолчанию (review.md §10) — недоступность модератора блокирует контент.
    moderation_fail_open: bool = False

    rate_limit_generate_per_minute: int = 5

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    runway_api_key: str = ""

    sync_api_key: str = ""
    sync_model: str = "lipsync-2"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
