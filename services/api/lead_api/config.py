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
    supabase_service_role_key: str = ""
    resume_bucket: str = "resumes"
    frontend_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    turnstile_secret_key: str = "1x0000000000000000000000000000000AA"
    turnstile_expected_action: str = "lead_submit"
    turnstile_allowed_hostnames: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )
    turnstile_timeout_seconds: float = 3.0
    turnstile_siteverify_url: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    public_lead_rate_limit_enabled: bool = True
    public_lead_rate_limit_max_requests: int = 20
    public_lead_rate_limit_window_seconds: int = 60
    public_lead_rate_limit_hmac_secret: str = "local-dev-rate-limit-secret-change-me"
    trusted_proxy_addresses: list[str] = Field(default_factory=list)
    fallback_intake_address: str = "intake.local@example.test"

    @field_validator(
        "frontend_origins",
        "turnstile_allowed_hostnames",
        "trusted_proxy_addresses",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("fallback_intake_address")
    @classmethod
    def require_fallback_intake_address(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("fallback_intake_address must not be empty")
        return normalized

    @property
    def required_configured(self) -> bool:
        return bool(
            self.database_url
            and self.supabase_url
            and self.supabase_anon_key
            and self.supabase_service_role_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
