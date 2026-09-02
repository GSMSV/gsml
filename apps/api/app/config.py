from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore")

    APP_TIMEZONE: str = "Asia/Seoul"
    CORS_ORIGINS: str = "http://localhost:5173"

    UPSTREAM_TIMEOUT: int = 600
    LLAMA_CHAT_TEMPLATE: str = "chatml"

    OAUTH_CLIENT_ID: str = ""
    OAUTH_CLIENT_SECRET: str = ""
    OAUTH_REDIRECT_URI: str = ""
    OAUTH_AUTH_BASE: str = ""
    OAUTH_RESOURCE_BASE: str = ""

    JWT_SECRET: str = "change-me"
    JWT_EXPIRE_HOURS: int = 24

    API_KEY_EXPIRE_DAYS: int = 30

    # 신규 유저의 1일 크레딧 한도. 단위는 크레딧(float).
    # 기본 단가 기준 1크레딧 = input 200만 토큰 = output 100만 토큰.
    DEFAULT_CREDIT_LIMIT: float = 1.0
    DEFAULT_MAX_CONCURRENT: int = 2

    # 토큰 100만 개당 크레딧 단가.
    # cached_input은 업스트림 KV 캐시 히트분이라 기본 무료(0.0)다.
    PRICE_INPUT_PER_1M: float = 0.5
    PRICE_CACHED_INPUT_PER_1M: float = 0.0
    PRICE_OUTPUT_PER_1M: float = 1.0

    REQUEST_LOG_RETENTION_DAYS: int = 30

    CONVERSATION_LOG_DIR: str = "/app/logs/conversations"

    DATABASE_URL: str = "sqlite:///./data/gsml.db"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
