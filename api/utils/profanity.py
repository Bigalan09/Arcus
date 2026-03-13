"""Profanity and blocklist checking for subdomain slugs.

Two layers of filtering:
1. ``better-profanity`` library word list (916 terms) – broad, maintained
   coverage with Unicode confusable variants.
2. Admin-managed blocklist stored in the database – custom terms added by the
   platform operator via the ``/admin/blocklist`` endpoints.

Both layers use substring matching so that a slug such as ``shitapp`` is
caught by the term ``shit``, regardless of word boundaries.
"""

from better_profanity import profanity as _profanity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Blocklist

# Initialise the library's default word list once at import time, then extract
# the plain strings for fast substring scanning. better_profanity stores words
# as VaryingString objects; the ._original attribute holds the base form.
_profanity.load_censor_words()
_BUILTIN_WORDS: frozenset[str] = frozenset(
    vs._original for vs in _profanity.CENSOR_WORDSET
)


def contains_builtin_profanity(slug: str) -> str | None:
    """Return the matched word if *slug* contains any term from the built-in
    profanity list as a substring, otherwise return None."""
    slug_lower = slug.lower()
    for word in _BUILTIN_WORDS:
        if word in slug_lower:
            return word
    return None


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
