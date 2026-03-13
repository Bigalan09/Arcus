"""RED tests for subdomain routes – must fail until implemented."""

import pytest


async def _setup_user_with_credits(client, email="subuser@example.com", credits=3):
    """Helper: create a user, grant credits, return user_id."""
    resp = await client.post("/users", json={"email": email})
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    await client.post("/credits/grant", json={"user_id": user_id, "amount": credits})
    return user_id


# ---------------------------------------------------------------------------
# POST /subdomains/purchase
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purchase_subdomain_success(client):
    """A user with credits can purchase a subdomain; balance is decremented."""
    user_id = await _setup_user_with_credits(client)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "myapp"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "myapp"
    assert data["user_id"] == user_id
    assert data["active"] is True

    # Verify credit was consumed.
    # Purchase another one to inspect the balance implicitly via a 402 later.
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "myapp2"})
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "myapp3"})
    no_credits = await client.post(
        "/subdomains/purchase", json={"user_id": user_id, "slug": "myapp4"}
    )
    assert no_credits.status_code == 402


@pytest.mark.asyncio
async def test_purchase_subdomain_no_credits(client):
    """A user with no credits gets 402."""
    resp = await client.post("/users", json={"email": "broke@example.com"})
    user_id = resp.json()["id"]
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "broke"})
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_purchase_subdomain_duplicate_slug(client):
    """Purchasing an already-taken slug returns 409."""
    user_id = await _setup_user_with_credits(client, "dup@example.com", 5)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "taken"})
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "taken"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_purchase_reserved_slug(client):
    """Purchasing a reserved slug returns 422."""
    user_id = await _setup_user_with_credits(client, "res@example.com", 5)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "www"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_purchase_slug_too_short(client):
    """A slug shorter than 3 characters returns 422."""
    user_id = await _setup_user_with_credits(client, "short@example.com", 5)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "ab"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_purchase_slug_invalid_chars(client):
    """A slug with uppercase or special characters returns 422."""
    user_id = await _setup_user_with_credits(client, "inv@example.com", 5)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "My-App"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /subdomains/{slug}/origin
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_origin_ip(client):
    """Setting a valid public IP origin succeeds."""
    user_id = await _setup_user_with_credits(client)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "origintest"})
    resp = await client.post(
        "/subdomains/origintest/origin",
        json={"origin_host": "203.0.113.10", "origin_port": 8080},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["origin_host"] == "203.0.113.10"
    assert data["origin_port"] == 8080


@pytest.mark.asyncio
async def test_set_origin_private_ip_rejected(client):
    """Setting a private IP as origin returns 422."""
    user_id = await _setup_user_with_credits(client)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "privtest"})
    resp = await client.post(
        "/subdomains/privtest/origin",
        json={"origin_host": "192.168.1.1", "origin_port": 80},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_origin_loopback_rejected(client):
    """Setting 127.0.0.1 as origin returns 422."""
    user_id = await _setup_user_with_credits(client)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "looptest"})
    resp = await client.post(
        "/subdomains/looptest/origin",
        json={"origin_host": "127.0.0.1", "origin_port": 80},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_origin_unknown_slug(client):
    """Setting an origin for a non-existent slug returns 404."""
    resp = await client.post(
        "/subdomains/doesnotexist/origin",
        json={"origin_host": "203.0.113.1", "origin_port": 80},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /subdomains
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_subdomains(client):
    """GET /subdomains?user_id=... returns the user's subdomains."""
    user_id = await _setup_user_with_credits(client, "list@example.com", 5)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "first"})
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "second"})

    resp = await client.get(f"/subdomains?user_id={user_id}")
    assert resp.status_code == 200
    slugs = [s["slug"] for s in resp.json()]
    assert "first" in slugs
    assert "second" in slugs


@pytest.mark.asyncio
async def test_list_subdomains_empty(client):
    """A user with no subdomains gets an empty list."""
    resp = await client.post("/users", json={"email": "empty@example.com"})
    user_id = resp.json()["id"]
    resp = await client.get(f"/subdomains?user_id={user_id}")
    assert resp.status_code == 200
    assert resp.json() == []
