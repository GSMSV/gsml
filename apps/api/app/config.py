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
    # 업스트림 /v1/chat/completions에 id_slot을 주입해 슬롯을 고정할지 여부.
    # llama-server 빌드가 OAI 엔드포인트의 id_slot 패스스루를 지원할 때만 의미가 있다
    # (미지원 빌드면 False로 두고 cache_prompt prefix-match에 맡긴다).
    UPSTREAM_SLOT_PINNING: bool = True

    OAUTH_CLIENT_ID: str = ""
    OAUTH_CLIENT_SECRET: str = ""
    OAUTH_REDIRECT_URI: str = ""
    OAUTH_AUTH_BASE: str = ""
    OAUTH_RESOURCE_BASE: str = ""

    JWT_SECRET: str = "change-me"
    JWT_EXPIRE_HOURS: int = 24

    API_KEY_EXPIRE_DAYS: int = 30

    DEFAULT_USAGE_LIMIT: int = 100_000
    DEFAULT_MAX_CONCURRENT: int = 2

    REQUEST_LOG_RETENTION_DAYS: int = 30

    CONVERSATION_LOG_DIR: str = "/app/logs/conversations"
    # 업스트림(llama-server/ollama) 원본 요청·응답을 raw-YYYY-MM-DD.jsonl로 기록할지 여부.
    RAW_UPSTREAM_LOG: bool = True

    DATABASE_URL: str = "sqlite:///./data/gsml.db"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
