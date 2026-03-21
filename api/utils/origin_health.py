"""Helpers for probing and storing origin health snapshots."""

from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal

import httpx


@dataclass(slots=True)
class OriginHealthSnapshot:
    """Last-known health state for a configured origin."""

    status: Literal["unknown", "healthy", "unreachable"]
    checked_at: datetime
    status_code: int | None
    latency_ms: int | None
    error: str | None


def _latency_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


async def probe_origin(host: str, port: int) -> OriginHealthSnapshot:
    """Probe ``host:port`` using plain HTTP and return a reachability snapshot."""
    started_at = perf_counter()
    checked_at = datetime.now(UTC)
    timeout = httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)
    url = f"http://{host}:{port}/"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, follow_redirects=False)
    except (httpx.HTTPError, OSError) as exc:
        return OriginHealthSnapshot(
            status="unreachable",
            checked_at=checked_at,
            status_code=None,
            latency_ms=_latency_ms(started_at),
            error=str(exc) or exc.__class__.__name__,
        )

    return OriginHealthSnapshot(
        status="healthy",
        checked_at=checked_at,
        status_code=response.status_code,
        latency_ms=_latency_ms(started_at),
        error=None,
    )
