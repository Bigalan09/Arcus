"""Credit management routes."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Credit, User, Webhook
from api.schemas import CreditGrant, CreditRequest, CreditRequestResponse, CreditResponse
from api.utils.deps import get_current_user, require_admin
from api.utils.webhooks import fire_webhooks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("", response_model=CreditResponse)
async def get_credits(
    user_id: uuid.UUID | None = Query(None, description="Admin: query another user's balance"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the credit balance for the authenticated user.

    Admins may pass ``user_id`` to query any user's balance.
    """
    if user_id and user_id != user.id:
        if user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot query other users' credits.")
        target = await db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        if target.role == "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin accounts do not use credits.",
            )
        target_id = user_id
    else:
        if user.role == "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin accounts do not use credits.",
            )
        target_id = user.id

    result = await db.execute(select(Credit).where(Credit.user_id == target_id))
    credit = result.scalar_one_or_none()
    if credit is None:
        credit = Credit(user_id=target_id, balance=0)
        db.add(credit)
        await db.commit()
        await db.refresh(credit)
        logger.warning("Auto-initialised missing credit record for user %s", target_id)

    return credit


@router.post("/grant", response_model=CreditResponse, status_code=status.HTTP_200_OK)
async def grant_credits(
    payload: CreditGrant,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add credits to a user's balance. Requires admin authentication."""
    target_user = await db.get(User, payload.user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    if target_user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin accounts do not use credits.",
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
async def request_credits(
    payload: CreditRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request additional credits (fires registered webhooks)."""
    if user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin accounts do not request credits.",
        )

    if user.role != "admin" and payload.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only request credits for your own account.",
        )

    target = await db.get(User, payload.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if target.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin accounts do not request credits.",
        )

    result = await db.execute(select(Webhook).where(Webhook.active.is_(True)))
    webhooks = result.scalars().all()

    webhook_payload = {"user_id": str(payload.user_id), "amount": payload.amount, "message": payload.message}
    fired = await fire_webhooks(webhooks, "credit.request", webhook_payload)

    logger.info("Credit request from user %s – %d webhook(s) fired", payload.user_id, fired)
    return CreditRequestResponse(user_id=payload.user_id, webhooks_fired=fired)
