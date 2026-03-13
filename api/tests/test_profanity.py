"""Tests for the profanity filter on subdomain slugs."""

from unittest.mock import patch

import pytest

from api.config import settings


async def _user_with_credits(client, admin_headers, email="pf@example.com"):
    resp = await client.post("/users", json={"email": email}, headers=admin_headers)
    uid = resp.json()["id"]
    await client.post("/credits/grant", json={"user_id": uid, "amount": 5}, headers=admin_headers)
    return uid


@pytest.mark.asyncio
async def test_clean_slug_still_passes(client, admin_headers):
    """A clean slug is unaffected by the profanity filter."""
    uid = await _user_with_credits(client, admin_headers)
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "coolapp"}, headers=admin_headers)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_builtin_profanity_exact_match_rejected(client, admin_headers):
    """A slug that exactly matches a built-in profanity word is rejected with 422."""
    uid = await _user_with_credits(client, admin_headers, "pf2@example.com")
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "hell"}, headers=admin_headers)
    assert resp.status_code == 422
    assert "profanity" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_hello_is_not_rejected_by_builtin_profanity_filter(client, admin_headers):
    """A clean slug must not be rejected just because it contains a profane prefix."""
    uid = await _user_with_credits(client, admin_headers, "pf3@example.com")
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "hello"}, headers=admin_headers)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_check_endpoint_matches_purchase_for_builtin_profanity(client, admin_headers):
    """The public availability check must report the same profanity rejection the purchase path enforces."""
    uid = await _user_with_credits(client, admin_headers, "pf6@example.com")

    check = await client.get("/subdomains/check?slug=hell")
    assert check.status_code == 200
    check_data = check.json()
    assert check_data["available"] is False
    assert check_data["reason"] == "profanity"

    purchase = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "hell"}, headers=admin_headers)
    assert purchase.status_code == 422
    assert purchase.json()["detail"] == check_data["detail"]


@pytest.mark.asyncio
async def test_blocklisted_word_blocks_purchase(client, admin_headers):
    """After an admin adds a word to the blocklist, slugs containing it are rejected."""
    uid = await _user_with_credits(client, admin_headers, "pf4@example.com")

    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "arcustest"}, headers=admin_headers)
    assert resp.status_code == 201

    await client.post(
        "/admin/blocklist",
        json={"words": ["arcus"]},
        headers=admin_headers,
    )

    uid2 = await _user_with_credits(client, admin_headers, "pf5@example.com")
    resp2 = await client.post("/subdomains/purchase", json={"user_id": uid2, "slug": "arcusbad"}, headers=admin_headers)
    assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_check_endpoint_matches_purchase_for_blocklist(client, admin_headers):
    """Blocklist rejections should be identical in availability and purchase flows."""
    uid = await _user_with_credits(client, admin_headers, "pf7@example.com")

    await client.post(
        "/admin/blocklist",
        json={"words": ["arcus"]},
        headers=admin_headers,
    )

    check = await client.get("/subdomains/check?slug=arcuslan")
    assert check.status_code == 200
    check_data = check.json()
    assert check_data["available"] is False
    assert check_data["reason"] == "blocklisted"

    purchase = await client.post(
        "/subdomains/purchase",
        json={"user_id": uid, "slug": "arcuslan"},
        headers=admin_headers,
    )
    assert purchase.status_code == 422
    assert purchase.json()["detail"] == check_data["detail"]


@pytest.mark.asyncio
async def test_check_endpoint_marks_hello_available(client):
    """Availability checks must not report 'hello' as profanity."""
    with patch.object(settings, "base_domain", "localhost"):
        resp = await client.get("/subdomains/check?slug=hello")

    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True
    assert data["reason"] is None
