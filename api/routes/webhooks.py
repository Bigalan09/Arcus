"""Webhook management routes.

Admin endpoints (system-wide webhooks) require admin JWT authentication.
Pro/admin user endpoints (user-owned webhooks) require pro or admin JWT.

Endpoints
---------
GET    /admin/webhooks           – list all system webhooks (admin)
POST   /admin/webhooks           – create a system webhook (admin)
GET    /admin/webhooks/{id}      – get a system webhook (admin)
PUT    /admin/webhooks/{id}      – update a system webhook (admin)
DELETE /admin/webhooks/{id}      – delete a system webhook (admin)

GET    /webhooks                 – list the current user's webhooks (pro+)
POST   /webhooks                 – create a user webhook (pro+)
PUT    /webhooks/{id}            – update a user webhook (pro+)
DELETE /webhooks/{id}            – delete a user webhook (pro+)
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import User, Webhook
from api.schemas import WebhookCreate, WebhookResponse, WebhookUpdate
from api.utils.deps import require_admin, require_pro_or_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])

# Events that only admins may subscribe to on user-owned webhooks
ADMIN_ONLY_EVENTS: frozenset[str] = frozenset({"credit.request"})


# ===========================================================================
# Admin – system-wide webhooks
# ===========================================================================


@router.get("/admin/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return all registered system webhooks."""
    result = await db.execute(
        select(Webhook).where(Webhook.user_id.is_(None)).order_by(Webhook.created_at)
    )
    return result.scalars().all()


@router.post("/admin/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Register a new system webhook."""
    events_str = ",".join(payload.events)
    webhook = Webhook(
        url=str(payload.url),
        secret=payload.secret,
        events=events_str,
        active=payload.active,
        user_id=None,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    logger.info("System webhook %s created for events: %s", webhook.id, events_str)
    return webhook


@router.get("/admin/webhooks/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return a single system webhook by ID."""
    webhook = await db.get(Webhook, webhook_id)
    if webhook is None or webhook.user_id is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")
    return webhook


@router.put("/admin/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Update an existing system webhook."""
    webhook = await db.get(Webhook, webhook_id)
    if webhook is None or webhook.user_id is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")

    if payload.url is not None:
        webhook.url = str(payload.url)
    if payload.secret is not None:
        webhook.secret = payload.secret
    if payload.events is not None:
        webhook.events = ",".join(payload.events)
    if payload.active is not None:
        webhook.active = payload.active

    await db.commit()
    await db.refresh(webhook)
    logger.info("System webhook %s updated", webhook_id)
    return webhook


@router.delete("/admin/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Permanently delete a system webhook."""
    webhook = await db.get(Webhook, webhook_id)
    if webhook is None or webhook.user_id is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")
    await db.delete(webhook)
    await db.commit()
    logger.info("System webhook %s deleted", webhook_id)


# ===========================================================================
# User-owned webhooks  (pro + admin only)
# ===========================================================================


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_user_webhooks(
    user: User = Depends(require_pro_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's webhook subscriptions."""
    result = await db.execute(
        select(Webhook).where(Webhook.user_id == user.id).order_by(Webhook.created_at)
    )
    return result.scalars().all()


@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_user_webhook(
    payload: WebhookCreate,
    user: User = Depends(require_pro_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a webhook subscription for the current user."""
    if user.role != "admin":
        restricted = ADMIN_ONLY_EVENTS.intersection(payload.events)
        if restricted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only admins can subscribe to event(s): {', '.join(sorted(restricted))}.",
            )
    events_str = ",".join(payload.events)
    webhook = Webhook(
        url=str(payload.url),
        secret=payload.secret,
        events=events_str,
        active=payload.active,
        user_id=user.id,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    logger.info("User %s created webhook %s for events: %s", user.id, webhook.id, events_str)
    return webhook


@router.put("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_user_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    user: User = Depends(require_pro_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update one of the current user's webhooks."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user.id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")

    if user.role != "admin" and payload.events is not None:
        restricted = ADMIN_ONLY_EVENTS.intersection(payload.events)
        if restricted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only admins can subscribe to event(s): {', '.join(sorted(restricted))}.",
            )

    if payload.url is not None:
        webhook.url = str(payload.url)
    if payload.secret is not None:
        webhook.secret = payload.secret
    if payload.events is not None:
        webhook.events = ",".join(payload.events)
    if payload.active is not None:
        webhook.active = payload.active

    await db.commit()
    await db.refresh(webhook)
    logger.info("User %s updated webhook %s", user.id, webhook_id)
    return webhook


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(require_pro_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete one of the current user's webhooks."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user.id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")
    await db.delete(webhook)
    await db.commit()
    logger.info("User %s deleted webhook %s", user.id, webhook_id)
