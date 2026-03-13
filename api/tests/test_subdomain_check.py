"""Tests for GET /subdomains/check."""

import pytest


async def _setup_user_with_credits(client, admin_headers, email="checkuser@example.com", credits=3):
    resp = await client.post("/users", json={"email": email}, headers=admin_headers)
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    await client.post("/credits/grant", json={"user_id": user_id, "amount": credits}, headers=admin_headers)
    return user_id


@pytest.mark.asyncio
async def test_check_slug_available(client):
    """GET /subdomains/check returns available=True for an unused slug (public endpoint)."""
    resp = await client.get("/subdomains/check?slug=freeone")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "freeone"
    assert data["available"] is True
    assert data["reason"] is None
    assert "domain" in data  # domain field present in response


@pytest.mark.asyncio
async def test_check_slug_taken(client, admin_headers):
    """GET /subdomains/check returns available=False for an already-purchased slug."""
    user_id = await _setup_user_with_credits(client, admin_headers)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "takenslug"}, headers=admin_headers)

    resp = await client.get("/subdomains/check?slug=takenslug")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "takenslug"
    assert data["available"] is False
    assert data["reason"] == "taken"
    assert "taken" in data["detail"].lower()


@pytest.mark.asyncio
async def test_check_slug_after_purchase(client, admin_headers):
    """After purchasing a slug it becomes unavailable."""
    user_id = await _setup_user_with_credits(client, admin_headers, "checkafter@example.com")

    before = await client.get("/subdomains/check?slug=newslug")
    assert before.json()["available"] is True

    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "newslug"}, headers=admin_headers)

    after = await client.get("/subdomains/check?slug=newslug")
    assert after.json()["available"] is False


@pytest.mark.asyncio
async def test_check_slug_reserved_reports_unavailable(client):
    """Reserved slugs should be rejected by the public availability check too."""
    resp = await client.get("/subdomains/check?slug=www")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["reason"] == "reserved"


@pytest.mark.asyncio
async def test_check_slug_invalid_domain_reports_unavailable(client):
    """Unconfigured domains should be rejected without pretending the slug is available."""
    resp = await client.get("/subdomains/check?slug=freeone&domain=notconfigured.example.com")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is False
    assert data["reason"] == "invalid_domain"
