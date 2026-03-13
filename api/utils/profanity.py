"""Profanity and blocklist checks for subdomain slugs."""

from better_profanity import profanity as _profanity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Blocklist

_profanity.load_censor_words()


def contains_builtin_profanity(slug: str) -> str | None:
    """Return *slug* when the built-in profanity detector flags it."""
    return slug if _profanity.contains_profanity(slug) else None


async def get_blocklisted_match(slug: str, db: AsyncSession) -> str | None:
    """Return the matched blocklist word if *slug* contains any admin-defined
    blocked word as a substring, otherwise return None."""
    result = await db.execute(select(Blocklist.word))
    words = result.scalars().all()
    slug_lower = slug.lower()
    for word in words:
        if word.lower() in slug_lower:
            return word
    return None


async def check_slug(slug: str, db: AsyncSession) -> None:
    """Raise ``ValueError`` if *slug* matches any profanity or blocklist entry.

    The message identifies which layer triggered the block.
    """
    match = contains_builtin_profanity(slug)
    if match:
        raise ValueError(
            f"The slug '{slug}' contains language that is not permitted (profanity filter)."
        )

    match = await get_blocklisted_match(slug, db)
    if match:
        raise ValueError(
            f"The slug '{slug}' contains a blocked term ('{match}') and cannot be purchased."
        )
