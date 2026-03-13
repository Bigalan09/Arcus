import json
from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass
class DomainConfig:
    """Configuration for a single managed domain."""

    domain: str
    cloudflare_zone_id: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://arcus:arcus@postgres:5432/arcus"
    cloudflare_api_token: str = ""

    # ---------------------------------------------------------------------------
    # Multi-domain support
    # ---------------------------------------------------------------------------
    # Set DOMAINS to a JSON array of objects, each with "domain" and
    # "cloudflare_zone_id" keys, to enable multiple managed domains.
    # Example:
    #   DOMAINS='[{"domain":"example.com","cloudflare_zone_id":"abc"},
    #             {"domain":"another.dev","cloudflare_zone_id":"def"}]'
    #
    # When DOMAINS is empty the legacy BASE_DOMAIN / CLOUDFLARE_ZONE_ID pair is
    # used as a single-entry fallback so existing deployments keep working.
    domains: str = ""

    # Single-domain fallback (kept for backward compatibility)
    cloudflare_zone_id: str = ""
    base_domain: str = "bigalan.dev"
    allow_private_origin_hosts: bool = False

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

    @property
    def configured_domains(self) -> list[DomainConfig]:
        """Return the list of configured domains.

        Parses the DOMAINS JSON env-var when set; otherwise falls back to the
        legacy BASE_DOMAIN + CLOUDFLARE_ZONE_ID pair.
        """
        if self.domains.strip():
            raw: list[dict] = json.loads(self.domains)
            return [DomainConfig(domain=d["domain"], cloudflare_zone_id=d["cloudflare_zone_id"]) for d in raw]
        return [DomainConfig(domain=self.base_domain, cloudflare_zone_id=self.cloudflare_zone_id)]

    @property
    def primary_domain(self) -> str:
        """The first (primary) configured domain."""
        return self.configured_domains[0].domain

    def get_zone_id_for_domain(self, domain: str) -> str | None:
        """Return the Cloudflare zone ID for *domain*, or None if not found."""
        for dc in self.configured_domains:
            if dc.domain == domain:
                return dc.cloudflare_zone_id
        return None


settings = Settings()
