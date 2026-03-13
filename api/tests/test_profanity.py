"""RED tests for the profanity filter on subdomain slugs."""

import pytest


async def _user_with_credits(client, email="pf@example.com"):
    resp = await client.post("/users", json={"email": email})
    uid = resp.json()["id"]
    await client.post("/credits/grant", json={"user_id": uid, "amount": 5})
    return uid


@pytest.mark.asyncio
async def test_clean_slug_still_passes(client):
    """A clean slug is unaffected by the profanity filter."""
    uid = await _user_with_credits(client)
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "coolapp"})
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_builtin_profanity_exact_match_rejected(client):
    """A slug that exactly matches a built-in profanity word is rejected with 422."""
    uid = await _user_with_credits(client, "pf2@example.com")
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "shitapp"})
    assert resp.status_code == 422
    assert "profanity" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_builtin_profanity_substring_rejected(client):
    """A slug containing a profanity word as a substring is rejected."""
    uid = await _user_with_credits(client, "pf3@example.com")
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "myfuckapp"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_blocklisted_word_blocks_purchase(client):
    """After an admin adds a word to the blocklist, slugs containing it are rejected."""
    import os
    api_key = os.environ.get("API_SECRET_KEY", "changeme")

    uid = await _user_with_credits(client, "pf4@example.com")

    # Slug is clean before blocklisting.
    resp = await client.post("/subdomains/purchase", json={"user_id": uid, "slug": "arcustest"})
    assert resp.status_code == 201

    # Admin adds "arcustest" to the blocklist.
    await client.post(
        "/admin/blocklist",
        json={"words": ["arcus"]},
        headers={"X-Api-Key": api_key},
    )

    uid2 = await _user_with_credits(client, "pf5@example.com")
    resp2 = await client.post("/subdomains/purchase", json={"user_id": uid2, "slug": "arcusbad"})
    assert resp2.status_code == 422
