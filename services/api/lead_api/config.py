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
    fallback_intake_address: str = ""
    email_provider: str = "local-smtp"
    email_from_address: str = "Alma Intake <intake@alma.local>"
    email_smtp_host: str = "127.0.0.1"
    email_smtp_port: int = 54325
    email_smtp_timeout_seconds: float = 5.0
    email_smtp_starttls: bool = False
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_worker_batch_size: int = 10
    email_worker_poll_seconds: float = 2.0
    email_worker_lease_seconds: int = 300
    email_worker_base_retry_seconds: int = 30
    email_worker_max_retry_seconds: int = 3600
    email_worker_database_pool_size: int = 2
    resend_api_key: str = ""
    resend_api_url: str = "https://api.resend.com/emails"
    resend_timeout_seconds: float = 10.0

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
    def normalize_fallback_intake_address(cls, value: str) -> str:
        return value.strip()

    @field_validator("email_provider")
    @classmethod
    def validate_email_provider(cls, value: str) -> str:
        if value not in {"local-smtp", "resend"}:
            raise ValueError("email_provider must be local-smtp or resend")
        return value

    @property
    def required_configured(self) -> bool:
        return bool(
            self.database_url
            and self.supabase_url
            and self.supabase_anon_key
            and self.supabase_service_role_key
            and self.fallback_intake_address
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
