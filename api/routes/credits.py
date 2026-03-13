"""Credit management routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Credit, User
from api.schemas import CreditGrant, CreditResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/credits", tags=["credits"])


@router.post("/grant", response_model=CreditResponse, status_code=status.HTTP_200_OK)
async def grant_credits(payload: CreditGrant, db: AsyncSession = Depends(get_db)):
    """Add credits to a user's balance."""
    # Verify the user exists.
    user = await db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    result = await db.execute(select(Credit).where(Credit.user_id == payload.user_id))
    credit = result.scalar_one_or_none()

    if credit is None:
        credit = Credit(user_id=payload.user_id, balance=payload.amount)
        db.add(credit)
    else:
        credit.balance += payload.amount

    await db.commit()
    await db.refresh(credit)
    logger.info("Granted %d credit(s) to user %s (new balance: %d)", payload.amount, payload.user_id, credit.balance)
    return credit
