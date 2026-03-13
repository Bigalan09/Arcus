"""Admin blocklist management routes.

All endpoints require an ``X-Api-Key`` header matching ``API_SECRET_KEY``.

Endpoints
---------
GET    /admin/blocklist           – list all blocked words
POST   /admin/blocklist           – add one or more words (JSON body)
DELETE /admin/blocklist/{word}    – remove a single word
GET    /admin/blocklist/export    – download the list as a CSV file
POST   /admin/blocklist/import    – upload a CSV file (?mode=append|replace)
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
from api.models import Blocklist
from api.schemas import BlocklistAddRequest, BlocklistEntry, BlocklistImportResult

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

@router.get("/blocklist", response_model=list[BlocklistEntry])
async def list_blocklist(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Return all words currently on the blocklist."""
    result = await db.execute(select(Blocklist).order_by(Blocklist.word))
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Add (single or batch)
# ---------------------------------------------------------------------------

@router.post("/blocklist", response_model=list[BlocklistEntry], status_code=status.HTTP_201_CREATED)
async def add_to_blocklist(
    payload: BlocklistAddRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Add one or more words to the blocklist. Duplicates are silently ignored."""
    for raw_word in payload.words:
        word = raw_word.strip().lower()
        if not word:
            continue
        existing = await db.execute(select(Blocklist).where(Blocklist.word == word))
        if existing.scalar_one_or_none() is not None:
            continue
        db.add(Blocklist(word=word))

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()

    # Re-fetch so created_at is populated.
    result = await db.execute(
        select(Blocklist).where(Blocklist.word.in_([w.strip().lower() for w in payload.words]))
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/blocklist/{word}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_blocklist(
    word: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Remove a single word from the blocklist."""
    result = await db.execute(select(Blocklist).where(Blocklist.word == word.lower()))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{word}' is not on the blocklist.",
        )
    await db.delete(entry)
    await db.commit()


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@router.get("/blocklist/export")
async def export_blocklist_csv(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Download the entire blocklist as a CSV file."""
    result = await db.execute(select(Blocklist.word).order_by(Blocklist.word))
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
        headers={"Content-Disposition": "attachment; filename=blocklist.csv"},
    )


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@router.post("/blocklist/import", response_model=BlocklistImportResult)
async def import_blocklist_csv(
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
        await db.execute(delete(Blocklist))

    imported = 0
    for word in words:
        existing = await db.execute(select(Blocklist).where(Blocklist.word == word))
        if existing.scalar_one_or_none() is not None:
            continue
        db.add(Blocklist(word=word))
        imported += 1

    await db.commit()
    logger.info("Blocklist CSV import (%s): %d word(s) imported", mode, imported)
    return BlocklistImportResult(imported=imported, mode=mode)
