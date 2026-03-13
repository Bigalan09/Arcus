"""Cloudflare DNS helper – creates A/CNAME records via the Cloudflare API."""

import logging

import httpx

from api.config import settings

logger = logging.getLogger(__name__)

_CF_API = "https://api.cloudflare.com/client/v4"


async def create_dns_record(slug: str, domain: str | None = None, proxy_ip: str | None = None) -> None:
    """Create a CNAME (or A) record for *slug*.*domain* pointing to the proxy.

    *domain* defaults to the primary configured domain when not supplied.

    If *proxy_ip* is None the record is a CNAME to the base domain itself so
    the wildcard record handles routing.  When an explicit IP is supplied an A
    record is created.

    Failures are logged but **do not** raise – the purchase still succeeds; the
    operator can manually fix DNS if needed.
    """
    actual_domain = domain or settings.primary_domain
    zone_id = settings.get_zone_id_for_domain(actual_domain)

    if not settings.cloudflare_api_token or not zone_id:
        logger.warning("Cloudflare credentials not configured for '%s' – skipping DNS record creation.", actual_domain)
        return

    fqdn = f"{slug}.{actual_domain}"
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
            "content": actual_domain,
            "ttl": 1,
            "proxied": True,
        }

    url = f"{_CF_API}/zones/{zone_id}/dns_records"
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
