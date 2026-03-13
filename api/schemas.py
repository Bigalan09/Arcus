import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

UserRole = Literal["normal", "pro", "admin"]


class UserCreate(BaseModel):
    email: EmailStr
    role: UserRole = "normal"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    must_change_password: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class SetupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="Initial admin password (≥ 8 characters)")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, description="New password (≥ 8 characters)")


# ---------------------------------------------------------------------------
# API Tokens
# ---------------------------------------------------------------------------


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="Friendly name for the token")


class ApiTokenResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiTokenCreatedResponse(ApiTokenResponse):
    token: str = Field(description="Raw token value – shown only once")


# ---------------------------------------------------------------------------
# Admin user management
# ---------------------------------------------------------------------------


class AdminUserCreate(BaseModel):
    email: EmailStr
    role: UserRole = "normal"


class AdminUserResponse(UserResponse):
    pass


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------

class CreditGrant(BaseModel):
    user_id: uuid.UUID
    amount: int = Field(gt=0, description="Number of credits to add (must be positive)")


class CreditResponse(BaseModel):
    user_id: uuid.UUID
    balance: int

    model_config = {"from_attributes": True}


class CreditRequest(BaseModel):
    user_id: uuid.UUID
    message: str | None = Field(default=None, max_length=500, description="Optional message describing why credits are needed")


class CreditRequestResponse(BaseModel):
    user_id: uuid.UUID
    webhooks_fired: int


# ---------------------------------------------------------------------------
# Subdomains
# ---------------------------------------------------------------------------

SLUG_PATTERN = r"^[a-z0-9]{3,32}$"

RESERVED_SLUGS = {"www", "api", "admin", "mail", "cdn", "app"}


class SubdomainPurchase(BaseModel):
    user_id: uuid.UUID
    slug: str = Field(pattern=SLUG_PATTERN)

    @field_validator("slug")
    @classmethod
    def slug_not_reserved(cls, v: str) -> str:
        if v in RESERVED_SLUGS:
            raise ValueError(f"'{v}' is a reserved subdomain and cannot be purchased")
        return v


class OriginSet(BaseModel):
    origin_host: str = Field(min_length=1, max_length=253)
    origin_port: int = Field(ge=1, le=65535)


class SubdomainResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    slug: str
    origin_host: str | None
    origin_port: int | None
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SubdomainCheckResponse(BaseModel):
    slug: str
    available: bool


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------

class BlocklistAddRequest(BaseModel):
    words: list[str] = Field(min_length=1, description="One or more words to block")


class BlocklistEntry(BaseModel):
    word: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BlocklistImportResult(BaseModel):
    imported: int
    mode: str


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

class WebhookCreate(BaseModel):
    url: HttpUrl
    secret: str | None = Field(default=None, description="Optional HMAC-SHA256 signing secret")
    events: list[str] = Field(default=["credit.request"], description="List of event types this webhook subscribes to")
    active: bool = True


class WebhookUpdate(BaseModel):
    url: HttpUrl | None = None
    secret: str | None = None
    events: list[str] | None = None
    active: bool | None = None


class WebhookResponse(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("events", mode="before")
    @classmethod
    def parse_events(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [e.strip() for e in v.split(",") if e.strip()]
        return list(v)  # type: ignore[arg-type]

