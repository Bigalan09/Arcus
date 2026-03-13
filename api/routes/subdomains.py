"""Subdomain management routes."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.database import get_db
from api.models import Credit, Subdomain, User, Webhook
from api.schemas import OriginSet, SubdomainCheckResponse, SubdomainPurchase, SubdomainResponse
from api.utils.cloudflare import create_dns_record
from api.utils.deps import get_current_user, get_current_user_optional
from api.utils.slug_policy import assess_slug_with_options
from api.utils.validation import validate_origin_host
from api.utils.webhooks import fire_webhooks

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

    if payload.ignore_content_filters and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to ignore content filters.",
        )

    domain = payload.domain or settings.primary_domain

    target_user = await db.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    assessment = await assess_slug_with_options(
        payload.slug,
        domain,
        db,
        ignore_content_filters=payload.ignore_content_filters,
    )
    if not assessment.available:
        status_code = (
            status.HTTP_409_CONFLICT
            if assessment.reason == "taken"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=assessment.detail)

    if target_user.role != "admin":
        result = await db.execute(select(Credit).where(Credit.user_id == payload.user_id))
        credit = result.scalar_one_or_none()
        if credit is None or credit.balance < 1:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Insufficient credits. Please top up your balance to purchase a subdomain.",
            )
        credit.balance -= 1

    subdomain = Subdomain(user_id=payload.user_id, slug=payload.slug, domain=domain)
    db.add(subdomain)

    try:
        await db.commit()
        await db.refresh(subdomain)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The subdomain '{payload.slug}.{domain}' is already taken.",
        ) from None

    logger.info("User %s purchased subdomain '%s.%s'", payload.user_id, payload.slug, domain)
    await create_dns_record(payload.slug, domain)
    result = await db.execute(select(Webhook).where(Webhook.active.is_(True)))
    webhooks = result.scalars().all()
    await fire_webhooks(
        webhooks,
        "subdomain.created",
        {
            "subdomain_id": str(subdomain.id),
            "user_id": str(subdomain.user_id),
            "slug": subdomain.slug,
            "domain": subdomain.domain,
        },
    )
    return subdomain


@router.post("/{slug}/origin", response_model=SubdomainResponse)
async def set_origin(
    slug: str,
    payload: OriginSet,
    domain: str | None = Query(None, description="Domain the subdomain belongs to (defaults to primary)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or update the origin server for a subdomain."""
    actual_domain = domain or settings.primary_domain
    result = await db.execute(select(Subdomain).where(Subdomain.slug == slug, Subdomain.domain == actual_domain))
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
    logger.info("Origin set for '%s.%s': %s:%d", slug, actual_domain, validated_host, payload.origin_port)
    result = await db.execute(select(Webhook).where(Webhook.active.is_(True)))
    webhooks = result.scalars().all()
    await fire_webhooks(
        webhooks,
        "subdomain.updated",
        {
            "subdomain_id": str(subdomain.id),
            "user_id": str(subdomain.user_id),
            "slug": subdomain.slug,
            "domain": subdomain.domain,
            "origin_host": subdomain.origin_host,
            "origin_port": subdomain.origin_port,
        },
    )
    return subdomain


@router.get("/check", response_model=SubdomainCheckResponse)
async def check_subdomain(
    slug: str = Query(..., description="Slug to check for availability"),
    domain: str | None = Query(None, description="Domain to check against (defaults to primary)"),
    ignore_content_filters: bool = Query(
        False,
        description="Admin only: bypass profanity and blocklist checks for this availability check",
    ),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Check whether a subdomain slug is available for a given domain (public endpoint)."""
    if ignore_content_filters and (user is None or user.role != "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to ignore content filters.",
        )

    assessment = await assess_slug_with_options(
        slug,
        domain,
        db,
        ignore_content_filters=ignore_content_filters,
    )
    return SubdomainCheckResponse(
        slug=assessment.slug,
        domain=assessment.domain,
        available=assessment.available,
        reason=assessment.reason,
        detail=assessment.detail,
    )


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


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subdomain(
    slug: str,
    domain: str | None = Query(None, description="Domain the subdomain belongs to (defaults to primary)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a subdomain."""
    actual_domain = domain or settings.primary_domain
    result = await db.execute(select(Subdomain).where(Subdomain.slug == slug, Subdomain.domain == actual_domain))
    subdomain = result.scalar_one_or_none()
    if subdomain is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subdomain not found.")

    if user.role != "admin" and subdomain.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own subdomains.",
        )

    subdomain_id = str(subdomain.id)
    subdomain_user_id = str(subdomain.user_id)
    subdomain_slug = subdomain.slug
    subdomain_domain = subdomain.domain

    await db.delete(subdomain)
    await db.commit()
    logger.info("Subdomain '%s.%s' deleted by user %s", subdomain_slug, subdomain_domain, user.id)

    result = await db.execute(select(Webhook).where(Webhook.active.is_(True)))
    webhooks = result.scalars().all()
    await fire_webhooks(
        webhooks,
        "subdomain.deleted",
        {
            "subdomain_id": subdomain_id,
            "user_id": subdomain_user_id,
            "slug": subdomain_slug,
            "domain": subdomain_domain,
        },
    )
