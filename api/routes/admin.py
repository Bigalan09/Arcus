"""Admin blacklist management routes.

All endpoints require an ``X-Api-Key`` header matching ``API_SECRET_KEY``.

Endpoints
---------
GET    /admin/blacklist           – list all blocked words
POST   /admin/blacklist           – add one or more words (JSON body)
DELETE /admin/blacklist/{word}    – remove a single word
GET    /admin/blacklist/export    – download the list as a CSV file
POST   /admin/blacklist/import    – upload a CSV file (?mode=append|replace)
"""

import csv
import io
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security, status
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.database import get_db
from api.models import Blacklist
from api.schemas import BlacklistAddRequest, BlacklistEntry, BlacklistImportResult

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def require_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    if not api_key or api_key != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
    return api_key


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("/blacklist", response_model=list[BlacklistEntry])
async def list_blacklist(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Return all words currently on the blacklist."""
    result = await db.execute(select(Blacklist).order_by(Blacklist.word))
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Add (single or batch)
# ---------------------------------------------------------------------------

@router.post("/blacklist", response_model=list[BlacklistEntry], status_code=status.HTTP_201_CREATED)
async def add_to_blacklist(
    payload: BlacklistAddRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Add one or more words to the blacklist. Duplicates are silently ignored."""
    added: list[Blacklist] = []
    for raw_word in payload.words:
        word = raw_word.strip().lower()
        if not word:
            continue
        existing = await db.execute(select(Blacklist).where(Blacklist.word == word))
        if existing.scalar_one_or_none() is not None:
            continue
        entry = Blacklist(word=word)
        db.add(entry)
        added.append(entry)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()

    # Re-fetch so created_at is populated.
    result = await db.execute(
        select(Blacklist).where(Blacklist.word.in_([w.strip().lower() for w in payload.words]))
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/blacklist/{word}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_blacklist(
    word: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Remove a single word from the blacklist."""
    result = await db.execute(select(Blacklist).where(Blacklist.word == word.lower()))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"'{word}' is not on the blacklist.")
    await db.delete(entry)
    await db.commit()


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@router.get("/blacklist/export")
async def export_blacklist_csv(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Download the entire blacklist as a CSV file."""
    result = await db.execute(select(Blacklist.word).order_by(Blacklist.word))
    words = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["word"])
    for word in words:
        writer.writerow([word])
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=blacklist.csv"},
    )


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@router.post("/blacklist/import", response_model=BlacklistImportResult)
async def import_blacklist_csv(
    request: Request,
    mode: Literal["append", "replace"] = Query(
        default="append",
        description="'append' adds new words to the existing list; 'replace' clears the list first.",
    ),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Import a CSV file of blocked words.

    The CSV must have a single ``word`` column (header optional).
    Lines starting with ``#`` and blank lines are ignored.
    """
    body = await request.body()
    text_body = body.decode("utf-8", errors="replace")

    words: list[str] = []
    reader = csv.reader(io.StringIO(text_body))
    for i, row in enumerate(reader):
        if not row:
            continue
        cell = row[0].strip()
        if not cell or cell.startswith("#"):
            continue
        if i == 0 and cell.lower() == "word":
            continue  # skip header row
        words.append(cell.lower())

    if mode == "replace":
        await db.execute(delete(Blacklist))

    imported = 0
    for word in words:
        existing = await db.execute(select(Blacklist).where(Blacklist.word == word))
        if existing.scalar_one_or_none() is not None:
            continue
        db.add(Blacklist(word=word))
        imported += 1

    await db.commit()
    logger.info("Blacklist CSV import (%s): %d word(s) imported", mode, imported)
    return BlacklistImportResult(imported=imported, mode=mode)
