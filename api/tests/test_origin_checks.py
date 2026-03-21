"""Tests for origin health probing."""

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_probe_origin_returns_healthy_snapshot():
    """Any HTTP response should count as a healthy reachable origin."""
    from api.utils.origin_health import probe_origin

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, follow_redirects):
            assert url == "http://203.0.113.10:8080/"
            assert follow_redirects is False
            return SimpleNamespace(status_code=404)

    with patch("api.utils.origin_health.httpx.AsyncClient", return_value=_MockClient()):
        snapshot = await probe_origin("203.0.113.10", 8080)

    assert snapshot.status == "healthy"
    assert snapshot.status_code == 404
    assert snapshot.error is None
    assert snapshot.checked_at is not None
    assert snapshot.latency_ms is not None
    assert snapshot.latency_ms >= 0


@pytest.mark.asyncio
async def test_probe_origin_returns_unreachable_snapshot_on_connect_error():
    """Connection failures should return an unreachable snapshot with an error message."""
    from api.utils.origin_health import probe_origin

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, follow_redirects):
            raise httpx.ConnectError("boom", request=httpx.Request("GET", url))

    with patch("api.utils.origin_health.httpx.AsyncClient", return_value=_MockClient()):
        snapshot = await probe_origin("198.51.100.20", 3000)

    assert snapshot.status == "unreachable"
    assert snapshot.status_code is None
    assert snapshot.error is not None
    assert "boom" in snapshot.error
    assert snapshot.checked_at is not None
    assert snapshot.latency_ms is not None
