"""Admin routes.

Blocklist management and user management require admin JWT authentication.

Endpoints
---------
GET    /admin/users                 – list all users
POST   /admin/users                 – create a user (emails temp password)
POST   /admin/users/{id}/reset-password – reset a user's password (resend email)
GET    /admin/blocklist             – list all blocked words
POST   /admin/blocklist             – add words
DELETE /admin/blocklist/{word}      – remove a word
GET    /admin/blocklist/export      – download CSV
POST   /admin/blocklist/import      – upload CSV
"""

import csv
import io
import logging
import uuid as _uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Blocklist, Credit, User, Webhook
from api.schemas import (
    AdminUserCreate,
    AdminUserResponse,
    AdminUserUpdate,
    BlocklistAddRequest,
    BlocklistEntry,
    BlocklistImportResult,
)
from api.utils.auth import generate_temp_password, hash_password
from api.utils.deps import require_admin
from api.utils.email import send_password_reset_email, send_welcome_email
from api.utils.webhooks import fire_webhooks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def _parse_uuid(value: str, detail: str = "Invalid user ID.") -> _uuid.UUID:
    try:
        return _uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail) from None


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all user accounts."""
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user_admin(
    payload: AdminUserCreate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user account.

    A random temporary password is generated and emailed to the user (via
    background task so the response is not blocked by SMTP).
    The user must change it on first login.
    """
    if payload.role == "admin":
        result = await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))
        if result.scalar_one() > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An admin user already exists. Only one admin is permitted.",
            )

    temp_password = generate_temp_password()
    user = User(
        email=payload.email,
        role=payload.role,
        password_hash=hash_password(temp_password),
        must_change_password=True,
    )
    db.add(user)
    try:
        await db.flush()
        if payload.role != "admin":
            db.add(Credit(user_id=user.id, balance=0))
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that e-mail address already exists.",
        ) from None

    logger.info("Admin %s created user %s (role=%s)", admin.id, user.email, user.role)
    background_tasks.add_task(send_welcome_email, user.email, temp_password)
    result = await db.execute(select(Webhook).where(Webhook.active.is_(True)))
    webhooks = result.scalars().all()
    await fire_webhooks(
        webhooks,
        "user.created",
        {"user_id": str(user.id), "email": user.email, "role": user.role},
    )
    return user


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user_admin(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return a single user account by ID."""
    uid = _parse_uuid(user_id)
    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user_admin(
    user_id: str,
    payload: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update mutable user fields (role, active)."""
    uid = _parse_uuid(user_id)
    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if payload.role is not None and payload.role != user.role:
        if payload.role == "admin":
            result = await db.execute(
                select(func.count()).select_from(User).where(User.role == "admin", User.id != user.id)
            )
            if result.scalar_one() > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An admin user already exists. Only one admin is permitted.",
                )
        if user.role == "admin" and payload.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot demote the only admin account.",
            )
        user.role = payload.role

    if payload.active is not None and payload.active != user.active:
        if user.id == admin.id and payload.active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account.",
            )
        if user.role == "admin" and payload.active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate the admin account.",
            )
        user.active = payload.active

    if payload.role == "admin":
        result = await db.execute(select(Credit).where(Credit.user_id == user.id))
        credit = result.scalar_one_or_none()
        if credit is not None:
            await db.delete(credit)

    if payload.role is not None and payload.role != "admin":
        result = await db.execute(select(Credit).where(Credit.user_id == user.id))
        credit = result.scalar_one_or_none()
        if credit is None:
            db.add(Credit(user_id=user.id, balance=0))

    await db.commit()
    await db.refresh(user)
    logger.info("Admin %s updated user %s (role=%s, active=%s)", admin.id, user.id, user.role, user.active)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_admin(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user account."""
    uid = _parse_uuid(user_id)
    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")
    if user.role == "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete the admin account.")

    await db.delete(user)
    await db.commit()
    logger.info("Admin %s deleted user %s", admin.id, uid)


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_user_password(
    user_id: str,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password: generate a new temp password and email it (non-blocking)."""
    uid = _parse_uuid(user_id)
    user = await db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    temp_password = generate_temp_password()
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    await db.commit()

    logger.info("Admin %s reset password for user %s", admin.id, user.id)
    background_tasks.add_task(send_password_reset_email, user.email, temp_password)


# ---------------------------------------------------------------------------
# Blocklist – List
# ---------------------------------------------------------------------------


@router.get("/blocklist", response_model=list[BlocklistEntry])
async def list_blocklist(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return all words currently on the blocklist."""
    result = await db.execute(select(Blocklist).order_by(Blocklist.word))
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Blocklist – Add
# ---------------------------------------------------------------------------


@router.post("/blocklist", response_model=list[BlocklistEntry], status_code=status.HTTP_201_CREATED)
async def add_to_blocklist(
    payload: BlocklistAddRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
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

    result = await db.execute(
        select(Blocklist).where(Blocklist.word.in_([w.strip().lower() for w in payload.words]))
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Blocklist – Delete
# ---------------------------------------------------------------------------


@router.delete("/blocklist/{word}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_blocklist(
    word: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
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
# Blocklist – CSV export
# ---------------------------------------------------------------------------


@router.get("/blocklist/export")
async def export_blocklist_csv(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
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
# Blocklist – CSV import
# ---------------------------------------------------------------------------


@router.post("/blocklist/import", response_model=BlocklistImportResult)
async def import_blocklist_csv(
    request: Request,
    mode: Literal["append", "replace"] = Query(
        default="append",
        description="'append' adds new words; 'replace' clears first.",
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Import a CSV file of blocked words."""
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
            continue
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
