from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogsSettings(BaseSettings):
    """Settings for log capture, read from environment variables or a .env file.

    Every variable is prefixed with LOGS_, e.g. LOGS_MONGODB_URL.
    """

    model_config = SettingsConfigDict(
        env_prefix="LOGS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "fastapi_logs"
    mongodb_collection: str = "request_logs"

    service_name: str = "fastapi-app"
    environment: str = "development"

    # Where the logs API is mounted, e.g. /api/v1/logs to sit under an existing API prefix
    api_prefix: str = "/api/logs"

    retention_days: int = 14
    # Comma-separated path prefixes that are not recorded
    exclude_paths: str = "/docs,/redoc,/openapi.json,/favicon.ico"
    capture_level: str = "INFO"
    # Also record print() output written while a request runs
    capture_print: bool = True
    # Also record uvicorn's own log lines: startup/shutdown as their own entries, and each request's access line
    # ('127.0.0.1:5000 - "GET /x HTTP/1.1" 200 OK') as a message on that request
    capture_server_logs: bool = True

    # Demo only: lets the UI insert fake logs (POST {api_prefix}/demo/seed). Leave off in real projects.
    enable_demo_data: bool = False

    # Background writer tuning
    batch_size: int = 100
    flush_interval_seconds: float = 1.0
    queue_max_size: int = 10_000

    @property
    def excluded_paths(self) -> list[str]:
        paths = [p.strip() for p in self.exclude_paths.split(",") if p.strip()]
        # Never record the logs UI's own API calls
        return [*paths, self.api_prefix]

    @field_validator("capture_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()


@lru_cache
def get_settings() -> LogsSettings:
    return LogsSettings()
