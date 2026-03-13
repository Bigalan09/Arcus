"""User management routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Credit, User
from api.schemas import UserCreate, UserResponse
from api.utils.deps import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Create a new user account. Requires admin authentication.

    For a richer admin flow (with auto-generated emailed passwords), use
    ``POST /admin/users`` instead.
    """
    if payload.role == "admin":
        result = await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))
        if result.scalar_one() > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An admin user already exists. Only one admin is permitted.",
            )

    user = User(email=payload.email, role=payload.role, must_change_password=False)
    db.add(user)
    try:
        await db.flush()
        if payload.role != "admin":
            credit = Credit(user_id=user.id, balance=0)
            db.add(credit)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        logger.warning("Duplicate e-mail address: %s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that e-mail address already exists.",
        ) from None
    logger.info("Created user %s (%s, role=%s)", user.id, user.email, user.role)
    return user
