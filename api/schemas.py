import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


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
