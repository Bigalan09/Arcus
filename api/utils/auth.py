"""Authentication utilities – password hashing, JWT, and API token helpers."""

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from api.config import settings

# ---------------------------------------------------------------------------
# Password hashing  (bcrypt via passlib)
# ---------------------------------------------------------------------------

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored *hashed* value."""
    return _pwd_ctx.verify(plain, hashed)


def generate_temp_password(length: int = 16) -> str:
    """Generate a random temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Return a signed JWT containing *data*."""
    payload = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT.  Raises ``jwt.InvalidTokenError`` on failure."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


# ---------------------------------------------------------------------------
# API tokens  (opaque bearer tokens, stored as SHA-256 hashes)
# ---------------------------------------------------------------------------

API_TOKEN_PREFIX = "arc_"


def generate_api_token() -> str:
    """Return a new random API token string (shown to the user once)."""
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    """Return the SHA-256 hex digest of *token* for safe DB storage."""
    return hashlib.sha256(token.encode()).hexdigest()
