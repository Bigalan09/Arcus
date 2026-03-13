"""Shared slug assessment logic for availability and purchase checks."""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.models import Subdomain
from api.schemas import RESERVED_SLUGS, SLUG_PATTERN
from api.utils.profanity import contains_builtin_profanity, get_blocklisted_match

_SLUG_RE = re.compile(SLUG_PATTERN)


@dataclass(slots=True)
class SlugAssessment:
    slug: str
    domain: str
    available: bool
    reason: str | None = None
    detail: str | None = None


async def assess_slug(slug: str, domain: str | None, db: AsyncSession) -> SlugAssessment:
    """Assess whether *slug* can be used on *domain*."""
    actual_domain = domain or settings.primary_domain
    configured = [item.domain for item in settings.configured_domains]

    if actual_domain not in configured:
        return SlugAssessment(
            slug=slug,
            domain=actual_domain,
            available=False,
            reason="invalid_domain",
            detail=f"Domain '{actual_domain}' is not configured. Available: {configured}",
        )

    if not _SLUG_RE.fullmatch(slug):
        return SlugAssessment(
            slug=slug,
            domain=actual_domain,
            available=False,
            reason="invalid_format",
            detail="Use 3-32 lowercase letters or numbers only.",
        )

    if slug in RESERVED_SLUGS:
        return SlugAssessment(
            slug=slug,
            domain=actual_domain,
            available=False,
            reason="reserved",
            detail=f"'{slug}' is a reserved subdomain and cannot be purchased.",
        )

    if contains_builtin_profanity(slug):
        return SlugAssessment(
            slug=slug,
            domain=actual_domain,
            available=False,
            reason="profanity",
            detail=f"The slug '{slug}' contains language that is not permitted (profanity filter).",
        )

    blocklisted = await get_blocklisted_match(slug, db)
    if blocklisted:
        return SlugAssessment(
            slug=slug,
            domain=actual_domain,
            available=False,
            reason="blocklisted",
            detail=f"The slug '{slug}' contains a blocked term ('{blocklisted}') and cannot be purchased.",
        )

    result = await db.execute(select(Subdomain.id).where(Subdomain.slug == slug, Subdomain.domain == actual_domain))
    if result.scalar_one_or_none() is not None:
        return SlugAssessment(
            slug=slug,
            domain=actual_domain,
            available=False,
            reason="taken",
            detail=f"The subdomain '{slug}.{actual_domain}' is already taken.",
        )

    return SlugAssessment(
        slug=slug,
        domain=actual_domain,
        available=True,
        detail=f"The subdomain '{slug}.{actual_domain}' is available.",
    )
