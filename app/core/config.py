from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CGSSB API"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./cgssb.db"
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    user_agent: str = "CGSSB-API/0.1 (+https://github.com/chandrakar-shubham/CGSSB_API)"
    api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
