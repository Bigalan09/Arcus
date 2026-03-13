"""RED tests for the Arcus Router – roles and interstitial behaviour."""

import pytest

from router.main import _extract_slug
from router.tests.conftest import insert_subdomain

BASE = "thesoftware.dev"


# ---------------------------------------------------------------------------
# Unit tests – _extract_slug
# ---------------------------------------------------------------------------

def test_extract_slug_valid():
    assert _extract_slug(f"myapp.{BASE}") == "myapp"


def test_extract_slug_strips_port():
    assert _extract_slug(f"myapp.{BASE}:443") == "myapp"


def test_extract_slug_not_subdomain():
    assert _extract_slug(BASE) is None


def test_extract_slug_deep_subdomain():
    """Two-level subdomains (a.b.thesoftware.dev) are not routed."""
    assert _extract_slug(f"a.b.{BASE}") is None


def test_extract_slug_unrelated_domain():
    assert _extract_slug("myapp.example.com") is None


# ---------------------------------------------------------------------------
# Integration tests – HTTP routing by role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_slug_returns_404(client):
    resp = await client.get("/", headers={"host": f"unknown.{BASE}"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_normal_user_gets_interstitial(client):
    """A subdomain owned by a normal user returns the Arcus interstitial HTML."""
    await insert_subdomain(role="normal", slug="normalsite")
    resp = await client.get("/", headers={"host": f"normalsite.{BASE}"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Arcus" in body
    assert "normalsite" in body
    assert "thesoftware.dev" in body


@pytest.mark.asyncio
async def test_pro_user_bypasses_interstitial(client):
    """A subdomain owned by a pro user is proxied directly (no interstitial)."""
    await insert_subdomain(role="pro", slug="prosite")
    resp = await client.get("/", headers={"host": f"prosite.{BASE}"})
    # Proxy attempted → mock returns 200 with plain-text body, not interstitial HTML
    assert resp.status_code == 200
    assert resp.content == b"origin ok"


@pytest.mark.asyncio
async def test_admin_user_bypasses_interstitial(client):
    """A subdomain owned by an admin user is proxied directly."""
    await insert_subdomain(role="admin", slug="adminsite")
    resp = await client.get("/", headers={"host": f"adminsite.{BASE}"})
    assert resp.status_code == 200
    assert resp.content == b"origin ok"


@pytest.mark.asyncio
async def test_normal_user_with_arcus_skip_cookie_bypasses_interstitial(client):
    """When the _arcus_pass cookie is set for a normal-user slug, proxy through."""
    await insert_subdomain(role="normal", slug="cookiesite")
    resp = await client.get(
        "/",
        headers={
            "host": f"cookiesite.{BASE}",
            "cookie": "_arcus_pass=cookiesite",
        },
    )
    assert resp.status_code == 200
    assert resp.content == b"origin ok"


@pytest.mark.asyncio
async def test_arcus_continue_param_sets_cookie_and_proxies(client):
    """?_arcus_skip=1 proxies the request and sets the _arcus_pass cookie."""
    await insert_subdomain(role="normal", slug="skipsite")
    resp = await client.get(
        "/?_arcus_skip=1",
        headers={"host": f"skipsite.{BASE}"},
    )
    assert resp.status_code == 200
    assert resp.content == b"origin ok"
    assert "_arcus_pass" in resp.headers.get("set-cookie", "")
