"""FastAPI dependency helpers for authentication and authorisation."""

import logging
from datetime import UTC, datetime

import jwt
from fastapi import Cookie, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import ApiToken, User
from api.utils.auth import decode_access_token, hash_api_token

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# API token limits by role
# ---------------------------------------------------------------------------

API_TOKEN_LIMITS: dict[str, int | None] = {
    "normal": 1,
    "pro": 5,
    "admin": None,  # unlimited
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _user_from_jwt(token: str, db: AsyncSession) -> User | None:
    try:
        payload = decode_access_token(token)
        user_id: str | None = payload.get("sub")
        if not user_id:
            return None
    except jwt.InvalidTokenError:
        return None
    import uuid as _uuid
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        return None
    return await db.get(User, uid)


async def _user_from_api_token(raw_token: str, db: AsyncSession) -> User | None:
    token_hash = hash_api_token(raw_token)
    result = await db.execute(select(ApiToken).where(ApiToken.token_hash == token_hash))
    api_token = result.scalar_one_or_none()
    if api_token is None:
        return None
    # Update last_used_at asynchronously (best-effort)
    api_token.last_used_at = datetime.now(UTC)
    await db.commit()
    return await db.get(User, api_token.user_id)


# ---------------------------------------------------------------------------
# Core dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    session_token: str | None = Cookie(default=None, alias="arcus_session"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current authenticated user from a Bearer JWT or API token.

    Accepts the token from:
    1. ``Authorization: Bearer <token>`` header
    2. ``arcus_session`` HTTP-only cookie (web frontend)
    """
    token: str | None = None

    if credentials:
        token = credentials.credentials
    elif session_token:
        token = session_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try JWT first
    user = await _user_from_jwt(token, db)

    # Fall back to API token
    if user is None and token.startswith("arc_"):
        user = await _user_from_api_token(token, db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    session_token: str | None = Cookie(default=None, alias="arcus_session"),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like get_current_user but returns None instead of raising 401."""
    try:
        return await get_current_user(credentials=credentials, session_token=session_token, db=db)
    except HTTPException:
        return None


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Raise 403 unless the authenticated user has the admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user


def require_pro_or_admin(user: User = Depends(get_current_user)) -> User:
    """Raise 403 unless the authenticated user is pro or admin."""
    if user.role not in ("pro", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pro or admin access required.",
        )
    return user
