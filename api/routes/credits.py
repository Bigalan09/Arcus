"""Credit management routes."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Credit, User, Webhook
from api.schemas import CreditGrant, CreditRequest, CreditRequestResponse, CreditResponse
from api.utils.webhooks import fire_webhooks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("", response_model=CreditResponse)
async def get_credits(
    user_id: uuid.UUID = Query(..., description="UUID of the user whose credit balance to retrieve"),
    db: AsyncSession = Depends(get_db),
):
    """Return the current credit balance for a user."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    result = await db.execute(select(Credit).where(Credit.user_id == user_id))
    credit = result.scalar_one_or_none()
    if credit is None:
        # Edge case: user exists but no credit row (e.g. created outside the API).
        # Auto-initialise to ensure consistency.
        credit = Credit(user_id=user_id, balance=0)
        db.add(credit)
        await db.commit()
        await db.refresh(credit)
        logger.warning("Auto-initialised missing credit record for user %s", user_id)

    return credit


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


@router.post("/request", response_model=CreditRequestResponse, status_code=status.HTTP_202_ACCEPTED)
async def request_credits(payload: CreditRequest, db: AsyncSession = Depends(get_db)):
    """Request additional credits.

    Validates the user exists then fires all active webhooks subscribed to the
    ``credit.request`` event so that an operator can review and fulfil the
    request.
    """
    user = await db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    result = await db.execute(select(Webhook).where(Webhook.active.is_(True)))
    webhooks = result.scalars().all()

    webhook_payload = {
        "user_id": str(payload.user_id),
        "message": payload.message,
    }
    fired = await fire_webhooks(webhooks, "credit.request", webhook_payload)

    logger.info("Credit request from user %s – %d webhook(s) fired", payload.user_id, fired)
    return CreditRequestResponse(user_id=payload.user_id, webhooks_fired=fired)
