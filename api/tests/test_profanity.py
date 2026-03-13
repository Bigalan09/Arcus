"""Tests for the profanity filter on subdomain slugs."""

import pytest


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
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "shitapp"}, headers=admin_headers)
    assert resp.status_code == 422
    assert "profanity" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_builtin_profanity_substring_rejected(client, admin_headers):
    """A slug containing a profanity word as a substring is rejected."""
    uid = await _user_with_credits(client, admin_headers, "pf3@example.com")
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "myfuckapp"}, headers=admin_headers)
    assert resp.status_code == 422


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
