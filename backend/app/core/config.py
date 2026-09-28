from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Development-only defaults. Production refuses to start while any of these is still in use.
_DEV_SECRET_KEY = "dev-only-secret-change-me-0123456789abcdef"  # noqa: S105 - refused in production
_DEV_PII_ENCRYPTION_KEY = "ZGV2LW9ubHktcGlpLWtleS1jaGFuZ2UtbWUtMDEyMzQ="


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Mastek Event Manager"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "mysql+pymysql://mastek:mastek@localhost:3306/mastek_events"

    # Signs staff access tokens, and keys OTP hashes and keyed lookups (mobile, IP).
    # Encrypts guest mobiles at rest (Fernet key).
    secret_key: str = _DEV_SECRET_KEY
    pii_encryption_key: str = _DEV_PII_ENCRYPTION_KEY

    # Staff login.
    access_token_expire_minutes: int = Field(default=30, ge=1, le=24 * 60)
    # Security officers sign in once per gate shift.
    officer_session_minutes: int = Field(default=8 * 60, ge=1, le=24 * 60)
    max_failed_login_attempts: int = Field(default=5, ge=1)
    lockout_minutes: int = Field(default=15, ge=1)
    # Comma-separated list of allowed frontend origins.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:4200"]

    # SMS delivery. "console" prints OTPs to stdout for local development and is refused in production.
    sms_provider: Literal["disabled", "console"] = "disabled"

    # OTP rules and anti-abuse caps (per mobile number, per client IP, and for the whole app per day).
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_per_mobile_per_hour: int = 5
    otp_max_per_mobile_per_day: int = 10
    otp_max_per_ip_per_hour: int = 20
    sms_daily_budget: int = 2000

    # Minutes before an event starts that gate scanning opens, and hours after the start it closes
    # when the event has no end time.
    gate_opens_minutes_before_start: int = 180
    gate_closes_hours_after_start_if_no_end: int = 12

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _refuse_unsafe_production_config(self) -> "Settings":
        if self.environment != "production":
            return self
        if self.secret_key == _DEV_SECRET_KEY or len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be set to a random value of at least 32 characters in production")
        if self.pii_encryption_key == _DEV_PII_ENCRYPTION_KEY:
            raise ValueError("PII_ENCRYPTION_KEY must be set in production")
        if self.sms_provider == "console":
            raise ValueError("SMS_PROVIDER=console prints OTPs and cannot be used in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()


def get_settings() -> Settings:
    return settings
