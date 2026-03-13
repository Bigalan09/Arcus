"""User management routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Credit, User
from api.schemas import UserCreate, UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    """Create a new user account."""
    user = User(email=payload.email)
    db.add(user)
    # Also initialise a credit ledger row for this user.
    try:
        await db.flush()
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
        )
    logger.info("Created user %s (%s)", user.id, user.email)
    return user
