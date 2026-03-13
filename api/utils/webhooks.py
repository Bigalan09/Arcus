"""Webhook delivery utility.

Fires HTTP POST requests to registered webhook URLs for a given event.
Failures are logged but do not raise so callers are never blocked.

If a webhook has a ``secret`` configured, a HMAC-SHA256 signature is added as:
    X-Arcus-Signature: sha256=<hex_digest>
where the digest is computed over the raw JSON body.
"""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)


def _sign(secret: str, body: bytes) -> str:
    """Return a ``sha256=<hex>`` HMAC signature for *body* using *secret*."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


async def fire_webhooks(webhooks: list, event: str, payload: dict) -> int:
    """Deliver *event* to every active webhook in *webhooks* that subscribes to it.

    Parameters
    ----------
    webhooks:
        Sequence of ``Webhook`` ORM instances (url, secret, events, active).
    event:
        The event name, e.g. ``"credit.request"``.
    payload:
        Arbitrary JSON-serialisable data to include in the webhook body.

    Returns
    -------
    int
        Number of webhooks successfully delivered.
    """
    envelope = {
        "event": event,
        "fired_at": datetime.now(UTC).isoformat(),
        "data": payload,
    }
    body = json.dumps(envelope).encode()

    fired = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for wh in webhooks:
            events = [e.strip() for e in wh.events.split(",") if e.strip()]
            if event not in events:
                continue
            if not wh.active:
                continue

            headers: dict[str, str] = {"Content-Type": "application/json"}
            if wh.secret:
                headers["X-Arcus-Signature"] = _sign(wh.secret, body)
            if getattr(wh, "reference", None):
                headers["X-Arcus-Webhook-Ref"] = wh.reference

            try:
                resp = await client.post(str(wh.url), content=body, headers=headers)
                if resp.is_success:
                    fired += 1
                    logger.info("Webhook %s fired for event '%s': HTTP %d", wh.id, event, resp.status_code)
                else:
                    logger.warning("Webhook %s returned HTTP %d for event '%s'", wh.id, resp.status_code, event)
            except Exception as exc:
                logger.error("Webhook %s delivery failed for event '%s': %s", wh.id, event, exc)

    return fired
