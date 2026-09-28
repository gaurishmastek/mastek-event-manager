from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Mastek Event Manager"
    database_url: str = "mysql+pymysql://mastek:mastek@localhost:3306/mastek_events"


settings = Settings()
