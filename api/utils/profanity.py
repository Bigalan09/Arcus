"""Profanity and blacklist checking for subdomain slugs.

Two layers of filtering:
1. Built-in word list – a curated set of commonly blocked terms.
2. Admin-managed blacklist stored in the database.

Both checks use substring matching so that, for example, a slug of
``shitapp`` is caught by the word ``shit``.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Blacklist

# ---------------------------------------------------------------------------
# Built-in profanity word list
# ---------------------------------------------------------------------------
# Kept deliberately minimal. Extend as needed.
_BUILTIN: frozenset[str] = frozenset({
    "shit", "fuck", "cunt", "bitch", "cock", "dick",
    "pussy", "asshole", "bastard", "whore", "slut",
    "nigger", "nigga", "faggot", "retard", "twat",
})


def contains_builtin_profanity(slug: str) -> str | None:
    """Return the matched word if *slug* contains a built-in profanity term, else None."""
    slug_lower = slug.lower()
    for word in _BUILTIN:
        if word in slug_lower:
            return word
    return None


async def get_blacklisted_match(slug: str, db: AsyncSession) -> str | None:
    """Return the matched blacklist word if *slug* contains any admin-defined blocked
    word as a substring, otherwise return None."""
    result = await db.execute(select(Blacklist.word))
    words = result.scalars().all()
    slug_lower = slug.lower()
    for word in words:
        if word.lower() in slug_lower:
            return word
    return None


async def check_slug(slug: str, db: AsyncSession) -> None:
    """Raise ``ValueError`` if *slug* matches any profanity or blacklist entry.

    The message identifies which layer triggered the block.
    """
    match = contains_builtin_profanity(slug)
    if match:
        raise ValueError(
            f"The slug '{slug}' contains language that is not permitted (profanity filter)."
        )

    match = await get_blacklisted_match(slug, db)
    if match:
        raise ValueError(
            f"The slug '{slug}' contains a blocked term ('{match}') and cannot be purchased."
        )
