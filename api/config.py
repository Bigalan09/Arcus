from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://arcus:arcus@postgres:5432/arcus"
    cloudflare_api_token: str = ""
    cloudflare_zone_id: str = ""
    base_domain: str = "bigalan.dev"
    api_secret_key: str = "changeme"

    # JWT
    jwt_secret_key: str = "change_me_jwt_secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Email (SMTP)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@arcus.local"
    smtp_use_tls: bool = True


settings = Settings()
