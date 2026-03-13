from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://arcus:arcus@postgres:5432/arcus"
    cloudflare_api_token: str = ""
    cloudflare_zone_id: str = ""
    base_domain: str = "bigalan.dev"
    api_secret_key: str = "changeme"


settings = Settings()
