"""Subdomain management routes."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Credit, Subdomain, User
from api.schemas import OriginSet, SubdomainCheckResponse, SubdomainPurchase, SubdomainResponse
from api.utils.cloudflare import create_dns_record
from api.utils.deps import get_current_user
from api.utils.profanity import check_slug
from api.utils.validation import validate_origin_host

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subdomains", tags=["subdomains"])


@router.post("/purchase", response_model=SubdomainResponse, status_code=status.HTTP_201_CREATED)
async def purchase_subdomain(
    payload: SubdomainPurchase,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Purchase a subdomain using 1 credit.

    Admins may purchase for any user_id; regular users can only purchase for themselves.
    """
    if user.role != "admin" and payload.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only purchase subdomains for your own account.",
        )

    target_user = await db.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    result = await db.execute(select(Credit).where(Credit.user_id == payload.user_id))
    credit = result.scalar_one_or_none()
    if credit is None or credit.balance < 1:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient credits. Please top up your balance to purchase a subdomain.",
        )

    credit.balance -= 1

    try:
        await check_slug(payload.slug, db)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    subdomain = Subdomain(user_id=payload.user_id, slug=payload.slug)
    db.add(subdomain)

    try:
        await db.commit()
        await db.refresh(subdomain)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The subdomain '{payload.slug}' is already taken.",
        ) from None

    logger.info("User %s purchased subdomain '%s'", payload.user_id, payload.slug)
    await create_dns_record(payload.slug)
    return subdomain


@router.post("/{slug}/origin", response_model=SubdomainResponse)
async def set_origin(
    slug: str,
    payload: OriginSet,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or update the origin server for a subdomain."""
    result = await db.execute(select(Subdomain).where(Subdomain.slug == slug))
    subdomain = result.scalar_one_or_none()
    if subdomain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subdomain not found.")

    if user.role != "admin" and subdomain.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only modify your own subdomains.",
        )

    try:
        validated_host = validate_origin_host(payload.origin_host)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    subdomain.origin_host = validated_host
    subdomain.origin_port = payload.origin_port
    await db.commit()
    await db.refresh(subdomain)
    logger.info("Origin set for '%s': %s:%d", slug, validated_host, payload.origin_port)
    return subdomain


@router.get("/check", response_model=SubdomainCheckResponse)
async def check_subdomain(
    slug: str = Query(..., description="Slug to check for availability"),
    db: AsyncSession = Depends(get_db),
):
    """Check whether a subdomain slug is available (public endpoint)."""
    result = await db.execute(select(Subdomain).where(Subdomain.slug == slug))
    taken = result.scalar_one_or_none() is not None
    return SubdomainCheckResponse(slug=slug, available=not taken)


@router.get("", response_model=list[SubdomainResponse])
async def list_subdomains(
    user_id: uuid.UUID | None = Query(None, description="Admin: list another user's subdomains"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List subdomains for the authenticated user.

    Admins may pass ``user_id`` to list another user's subdomains.
    """
    if user_id and user_id != user.id:
        if user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot query other users' subdomains.")
        target_id = user_id
    else:
        target_id = user.id

    result = await db.execute(select(Subdomain).where(Subdomain.user_id == target_id))
    return result.scalars().all()
