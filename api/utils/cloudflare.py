"""Cloudflare DNS helper – creates A/CNAME records via the Cloudflare API."""

import logging

import httpx

from api.config import settings

logger = logging.getLogger(__name__)

_CF_API = "https://api.cloudflare.com/client/v4"


async def create_dns_record(slug: str, proxy_ip: str | None = None) -> None:
    """Create a CNAME (or A) record for *slug*.*BASE_DOMAIN* pointing to the proxy.

    If *proxy_ip* is None the record is a CNAME to the base domain itself so
    the wildcard record handles routing.  When an explicit IP is supplied an A
    record is created.

    Failures are logged but **do not** raise – the purchase still succeeds; the
    operator can manually fix DNS if needed.
    """
    if not settings.cloudflare_api_token or not settings.cloudflare_zone_id:
        logger.warning("Cloudflare credentials not configured – skipping DNS record creation.")
        return

    fqdn = f"{slug}.{settings.base_domain}"
    headers = {
        "Authorization": f"Bearer {settings.cloudflare_api_token}",
        "Content-Type": "application/json",
    }

    if proxy_ip:
        payload = {
            "type": "A",
            "name": fqdn,
            "content": proxy_ip,
            "ttl": 1,
            "proxied": True,
        }
    else:
        payload = {
            "type": "CNAME",
            "name": fqdn,
            "content": settings.base_domain,
            "ttl": 1,
            "proxied": True,
        }

    url = f"{_CF_API}/zones/{settings.cloudflare_zone_id}/dns_records"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
            data = resp.json()
            if resp.status_code in (200, 201) and data.get("success"):
                logger.info("Created DNS record %s for %s", payload["type"], fqdn)
            else:
                logger.error("Cloudflare DNS creation failed for %s: %s", fqdn, data)
    except Exception as exc:
        logger.error("Cloudflare DNS request failed for %s: %s", fqdn, exc)
