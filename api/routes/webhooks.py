"""Admin webhook management routes.

All endpoints require an ``X-Api-Key`` header matching ``API_SECRET_KEY``.

Endpoints
---------
GET    /admin/webhooks           – list all webhooks
POST   /admin/webhooks           – create a new webhook
GET    /admin/webhooks/{id}      – get a single webhook by ID
PUT    /admin/webhooks/{id}      – update a webhook
DELETE /admin/webhooks/{id}      – delete a webhook
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import Webhook
from api.routes.admin import require_api_key
from api.schemas import WebhookCreate, WebhookResponse, WebhookUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Return all registered webhooks."""
    result = await db.execute(select(Webhook).order_by(Webhook.created_at))
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Register a new webhook."""
    events_str = ",".join(payload.events)
    webhook = Webhook(
        url=str(payload.url),
        secret=payload.secret,
        events=events_str,
        active=payload.active,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    logger.info("Webhook %s created for events: %s", webhook.id, events_str)
    return webhook


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------

@router.get("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Return a single webhook by ID."""
    webhook = await db.get(Webhook, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")
    return webhook


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.put("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Update an existing webhook. Only provided fields are changed."""
    webhook = await db.get(Webhook, webhook_id)
    if webhook is None:
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
    logger.info("Webhook %s updated", webhook_id)
    return webhook


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
):
    """Permanently delete a webhook."""
    webhook = await db.get(Webhook, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")
    await db.delete(webhook)
    await db.commit()
    logger.info("Webhook %s deleted", webhook_id)
