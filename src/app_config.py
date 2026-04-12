from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "relivo-be-server"
    version: str = "0.1.0"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/relivo"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


settings = Settings()
