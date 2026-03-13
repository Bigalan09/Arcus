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
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db
from api.models import User, Webhook
from api.schemas import WebhookCreate, WebhookEventOption, WebhookResponse, WebhookUpdate
from api.utils.deps import require_admin, require_pro_or_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])

# Events that only admins may subscribe to on user-owned webhooks
ADMIN_ONLY_EVENTS: frozenset[str] = frozenset({"credits.requested", "user.created"})

WEBHOOK_EVENTS: tuple[WebhookEventOption, ...] = (
    WebhookEventOption(key="credits.requested", label="Credits Requested", admin_only=True),
    WebhookEventOption(key="user.created", label="User Created", admin_only=True),
    WebhookEventOption(key="subdomain.created", label="Subdomain Created", admin_only=False),
    WebhookEventOption(key="subdomain.updated", label="Subdomain Updated", admin_only=False),
    WebhookEventOption(key="subdomain.deleted", label="Subdomain Deleted", admin_only=False),
    WebhookEventOption(key="credits.granted", label="Credits Granted", admin_only=False),
    WebhookEventOption(key="token.created", label="Token Created", admin_only=False),
    WebhookEventOption(key="token.revoked", label="Token Revoked", admin_only=False),
    WebhookEventOption(key="token.expired", label="Token Expired", admin_only=False),
)
WEBHOOK_EVENT_KEYS: frozenset[str] = frozenset(ev.key for ev in WEBHOOK_EVENTS)


def _normalise_reference(reference: str | None) -> str | None:
    if reference is None:
        return None
    ref = reference.strip()
    return ref or None


def _validate_events(events: list[str]) -> list[str]:
    cleaned = []
    seen: set[str] = set()
    for event in events:
        key = event.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(key)
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one event is required.")
    invalid = [e for e in cleaned if e not in WEBHOOK_EVENT_KEYS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported event(s): {', '.join(sorted(invalid))}.",
        )
    return cleaned


async def _ensure_reference_unique(
    *,
    db: AsyncSession,
    user_id: uuid.UUID | None,
    reference: str | None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    if reference is None:
        return

    conditions = [Webhook.reference == reference]
    if exclude_id is not None:
        conditions.append(Webhook.id != exclude_id)

    if user_id is None:
        conditions.append(Webhook.user_id.is_(None))
    else:
        conditions.append(Webhook.user_id == user_id)

    result = await db.execute(select(Webhook).where(and_(*conditions)))
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Webhook reference '{reference}' is already in use.",
        )


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


@router.get("/admin/webhooks/events", response_model=list[WebhookEventOption])
async def list_webhook_events_admin(
    _: User = Depends(require_admin),
):
    """Return all supported webhook events for admin users."""
    return list(WEBHOOK_EVENTS)


@router.post("/admin/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Register a new system webhook."""
    events = _validate_events(payload.events)
    reference = _normalise_reference(payload.reference)
    await _ensure_reference_unique(db=db, user_id=None, reference=reference)
    events_str = ",".join(events)
    webhook = Webhook(
        url=str(payload.url),
        reference=reference,
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
    if payload.reference is not None:
        reference = _normalise_reference(payload.reference)
        await _ensure_reference_unique(db=db, user_id=None, reference=reference, exclude_id=webhook.id)
        webhook.reference = reference
    if payload.secret is not None:
        webhook.secret = payload.secret
    if payload.events is not None:
        webhook.events = ",".join(_validate_events(payload.events))
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


@router.get("/webhooks/events", response_model=list[WebhookEventOption])
async def list_webhook_events(
    user: User = Depends(require_pro_or_admin),
):
    """Return supported webhook events for the current role."""
    if user.role == "admin":
        return list(WEBHOOK_EVENTS)
    return [ev for ev in WEBHOOK_EVENTS if not ev.admin_only]


@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_user_webhook(
    payload: WebhookCreate,
    user: User = Depends(require_pro_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a webhook subscription for the current user."""
    events = _validate_events(payload.events)
    reference = _normalise_reference(payload.reference)
    await _ensure_reference_unique(db=db, user_id=user.id, reference=reference)

    if user.role != "admin":
        restricted = ADMIN_ONLY_EVENTS.intersection(events)
        if restricted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only admins can subscribe to event(s): {', '.join(sorted(restricted))}.",
            )
    events_str = ",".join(events)
    webhook = Webhook(
        url=str(payload.url),
        reference=reference,
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

    if payload.reference is not None:
        reference = _normalise_reference(payload.reference)
        await _ensure_reference_unique(db=db, user_id=user.id, reference=reference, exclude_id=webhook.id)
        webhook.reference = reference

    if user.role != "admin" and payload.events is not None:
        candidate_events = _validate_events(payload.events)
        restricted = ADMIN_ONLY_EVENTS.intersection(candidate_events)
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
        webhook.events = ",".join(_validate_events(payload.events))
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
