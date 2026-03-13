"""API token management routes.

Limits
------
normal : 1 token
pro    : 5 tokens
admin  : unlimited

Endpoints
---------
POST   /tokens        – create a new API token (value shown once)
GET    /tokens        – list the current user's tokens (hashes hidden)
DELETE /tokens/{id}   – revoke a token
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import ApiToken, User
from api.schemas import ApiTokenCreate, ApiTokenCreatedResponse, ApiTokenResponse
from api.utils.auth import generate_api_token, hash_api_token
from api.utils.deps import API_TOKEN_LIMITS, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.post("", response_model=ApiTokenCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: ApiTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API token for the authenticated user.

    The raw token is returned exactly once; only a hash is stored.
    """
    limit = API_TOKEN_LIMITS.get(user.role)
    if limit is not None:
        result = await db.execute(select(ApiToken).where(ApiToken.user_id == user.id))
        existing_count = len(result.scalars().all())
        if existing_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Token limit reached. Your plan allows {limit} token(s).",
            )

    raw_token = generate_api_token()
    token_hash = hash_api_token(raw_token)

    api_token = ApiToken(user_id=user.id, name=payload.name, token_hash=token_hash)
    db.add(api_token)
    await db.commit()
    await db.refresh(api_token)

    logger.info("API token '%s' created for user %s", payload.name, user.id)

    return ApiTokenCreatedResponse(
        id=api_token.id,
        name=api_token.name,
        token=raw_token,
        created_at=api_token.created_at,
    )


@router.get("", response_model=list[ApiTokenResponse])
async def list_tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's API tokens (raw values are never returned)."""
    result = await db.execute(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at)
    )
    return result.scalars().all()


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke (delete) one of the current user's API tokens."""
    import uuid as _uuid

    try:
        tid = _uuid.UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid token ID.") from None

    result = await db.execute(
        select(ApiToken).where(ApiToken.id == tid, ApiToken.user_id == user.id)
    )
    api_token = result.scalar_one_or_none()
    if api_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found.")

    await db.delete(api_token)
    await db.commit()
    logger.info("API token %s revoked by user %s", token_id, user.id)
