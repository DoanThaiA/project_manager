from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Project Manager API"
    environment: str = "development"
    debug: bool = False

    # Server PostgreSQL dùng chung với ai_carbon_analyst (cổng 5433, chỉ localhost); mật khẩu đặt qua .env
    database_url: str = "postgresql+asyncpg://pm_user:CHANGE_ME@localhost:5433/project_manager"

    secret_key: str = "change-me-to-a-random-64-char-secret"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
