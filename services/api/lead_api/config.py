from functools import lru_cache

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        extra="ignore",
        enable_decoding=False,
    )

    app_env: str = "local"
    database_url: str = Field(default="postgresql://app_api:local_app_api_password@127.0.0.1:54322/postgres")
    supabase_url: AnyHttpUrl = "http://127.0.0.1:54321"
    supabase_anon_key: str = ""
    frontend_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    @field_validator("frontend_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def required_configured(self) -> bool:
        return bool(self.database_url and self.supabase_url and self.supabase_anon_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
