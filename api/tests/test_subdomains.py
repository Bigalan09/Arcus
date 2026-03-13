"""Tests for subdomain routes."""

from unittest.mock import patch

import pytest

from api.config import settings


async def _setup_user_with_credits(client, admin_headers, email="subuser@example.com", credits=3):
    """Helper: create a user (as admin), grant credits, return user_id."""
    resp = await client.post("/users", json={"email": email}, headers=admin_headers)
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    await client.post("/credits/grant", json={"user_id": user_id, "amount": credits}, headers=admin_headers)
    return user_id


# ---------------------------------------------------------------------------
# POST /subdomains/purchase
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purchase_subdomain_success(client, admin_headers):
    """A user with credits can purchase a subdomain; balance is decremented."""
    user_id = await _setup_user_with_credits(client, admin_headers)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "myapp"}, headers=admin_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "myapp"
    assert data["user_id"] == user_id
    assert data["active"] is True
    assert "domain" in data  # domain field is present in response

    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "myapp2"}, headers=admin_headers)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "myapp3"}, headers=admin_headers)
    no_credits = await client.post(
        "/subdomains/purchase", json={"user_id": user_id, "slug": "myapp4"}, headers=admin_headers
    )
    assert no_credits.status_code == 402


@pytest.mark.asyncio
async def test_purchase_subdomain_no_credits(client, admin_headers):
    """A user with no credits gets 402."""
    resp = await client.post("/users", json={"email": "broke@example.com"}, headers=admin_headers)
    user_id = resp.json()["id"]
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "broke"}, headers=admin_headers)
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_admin_purchase_is_unlimited(client, admin_headers):
    """Admin users can purchase subdomains without credits."""
    me = await client.get("/auth/me", headers=admin_headers)
    assert me.status_code == 200
    admin_id = me.json()["id"]

    first = await client.post("/subdomains/purchase", json={"user_id": admin_id, "slug": "admone"}, headers=admin_headers)
    second = await client.post("/subdomains/purchase", json={"user_id": admin_id, "slug": "admtwo"}, headers=admin_headers)
    third = await client.post("/subdomains/purchase", json={"user_id": admin_id, "slug": "admthree"}, headers=admin_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 201


@pytest.mark.asyncio
async def test_purchase_subdomain_duplicate_slug(client, admin_headers):
    """Purchasing an already-taken slug returns 409."""
    user_id = await _setup_user_with_credits(client, admin_headers, "dup@example.com", 5)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "taken"}, headers=admin_headers)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "taken"}, headers=admin_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_purchase_reserved_slug(client, admin_headers):
    """Purchasing a reserved slug returns 422."""
    user_id = await _setup_user_with_credits(client, admin_headers, "res@example.com", 5)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "www"}, headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_purchase_slug_too_short(client, admin_headers):
    """A slug shorter than 3 characters returns 422."""
    user_id = await _setup_user_with_credits(client, admin_headers, "short@example.com", 5)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "ab"}, headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_purchase_slug_invalid_chars(client, admin_headers):
    """A slug with uppercase or special characters returns 422."""
    user_id = await _setup_user_with_credits(client, admin_headers, "inv@example.com", 5)
    resp = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "My-App"}, headers=admin_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /subdomains/{slug}/origin
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_origin_ip(client, admin_headers):
    """Setting a valid public IP origin succeeds."""
    user_id = await _setup_user_with_credits(client, admin_headers)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "origintest"}, headers=admin_headers)
    resp = await client.post(
        "/subdomains/origintest/origin",
        json={"origin_host": "203.0.113.10", "origin_port": 8080},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["origin_host"] == "203.0.113.10"
    assert data["origin_port"] == 8080


@pytest.mark.asyncio
async def test_set_origin_private_ip_rejected(client, admin_headers):
    """Setting a private IP as origin returns 422."""
    user_id = await _setup_user_with_credits(client, admin_headers)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "privtest"}, headers=admin_headers)
    resp = await client.post(
        "/subdomains/privtest/origin",
        json={"origin_host": "192.168.1.1", "origin_port": 80},
        headers=admin_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_origin_loopback_rejected(client, admin_headers):
    """Setting 127.0.0.1 as origin returns 422."""
    user_id = await _setup_user_with_credits(client, admin_headers)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "looptest"}, headers=admin_headers)
    resp = await client.post(
        "/subdomains/looptest/origin",
        json={"origin_host": "127.0.0.1", "origin_port": 80},
        headers=admin_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_set_origin_loopback_allowed_in_local_dev(client, admin_headers):
    """Local development mode should allow loopback origins."""
    user_id = await _setup_user_with_credits(client, admin_headers, "localorigin@example.com")
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "localtest"}, headers=admin_headers)

    with patch.object(settings, "allow_private_origin_hosts", True):
        resp = await client.post(
            "/subdomains/localtest/origin",
            json={"origin_host": "127.0.0.1", "origin_port": 3000},
            headers=admin_headers,
        )

    assert resp.status_code == 200
    assert resp.json()["origin_host"] == "127.0.0.1"
    assert resp.json()["origin_port"] == 3000


@pytest.mark.asyncio
async def test_set_origin_unknown_slug(client, admin_headers):
    """Setting an origin for a non-existent slug returns 404."""
    resp = await client.post(
        "/subdomains/doesnotexist/origin",
        json={"origin_host": "203.0.113.1", "origin_port": 80},
        headers=admin_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /subdomains
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_subdomains(client, admin_headers):
    """GET /subdomains?user_id=... (admin) returns the user's subdomains."""
    user_id = await _setup_user_with_credits(client, admin_headers, "list@example.com", 5)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "first"}, headers=admin_headers)
    await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "second"}, headers=admin_headers)

    resp = await client.get(f"/subdomains?user_id={user_id}", headers=admin_headers)
    assert resp.status_code == 200
    slugs = [s["slug"] for s in resp.json()]
    assert "first" in slugs
    assert "second" in slugs


@pytest.mark.asyncio
async def test_list_subdomains_empty(client, admin_headers):
    """A user with no subdomains gets an empty list."""
    resp = await client.post("/users", json={"email": "empty@example.com"}, headers=admin_headers)
    user_id = resp.json()["id"]
    resp = await client.get(f"/subdomains?user_id={user_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# DELETE /subdomains/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_subdomain_success(client, admin_headers):
    user_id = await _setup_user_with_credits(client, admin_headers, "delete@example.com", 2)
    created = await client.post("/subdomains/purchase", json={"user_id": user_id, "slug": "deleteone"}, headers=admin_headers)
    assert created.status_code == 201

    deleted = await client.delete("/subdomains/deleteone", headers=admin_headers)
    assert deleted.status_code == 204

    listed = await client.get(f"/subdomains?user_id={user_id}", headers=admin_headers)
    assert listed.status_code == 200
    assert "deleteone" not in [s["slug"] for s in listed.json()]


@pytest.mark.asyncio
async def test_delete_subdomain_forbidden_for_non_owner(client, admin_headers, normal_user):
    owner_id = await _setup_user_with_credits(client, admin_headers, "owner-sub@example.com", 2)
    created = await client.post(
        "/subdomains/purchase",
        json={"user_id": owner_id, "slug": "owneronly"},
        headers=admin_headers,
    )
    assert created.status_code == 201

    forbidden = await client.delete("/subdomains/owneronly", headers=normal_user["headers"])
    assert forbidden.status_code == 403


# ---------------------------------------------------------------------------
# Multi-domain tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purchase_subdomain_uses_primary_domain_by_default(client, admin_headers):
    """When no domain is specified the primary configured domain is used."""
    from api.config import settings

    user_id = await _setup_user_with_credits(client, admin_headers, "domaindefault@example.com", 2)
    resp = await client.post(
        "/subdomains/purchase",
        json={"user_id": user_id, "slug": "defaultdom"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["domain"] == settings.primary_domain


@pytest.mark.asyncio
async def test_purchase_subdomain_invalid_domain_rejected(client, admin_headers):
    """Purchasing a subdomain on an unconfigured domain returns 422."""
    user_id = await _setup_user_with_credits(client, admin_headers, "invdom@example.com", 2)
    resp = await client.post(
        "/subdomains/purchase",
        json={"user_id": user_id, "slug": "invdomslug", "domain": "notconfigured.example.com"},
        headers=admin_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_same_slug_different_domains_are_independent(client, admin_headers):
    """The same slug can be purchased on different configured domains."""
    import json
    from unittest.mock import patch

    from api.config import settings

    two_domains_json = json.dumps([
        {"domain": "bigalan.dev", "cloudflare_zone_id": ""},
        {"domain": "another.dev", "cloudflare_zone_id": ""},
    ])
    user_id = await _setup_user_with_credits(client, admin_headers, "multidomain@example.com", 4)

    with patch.object(settings, "domains", two_domains_json):
        resp1 = await client.post(
            "/subdomains/purchase",
            json={"user_id": user_id, "slug": "shared", "domain": "bigalan.dev"},
            headers=admin_headers,
        )
        resp2 = await client.post(
            "/subdomains/purchase",
            json={"user_id": user_id, "slug": "shared", "domain": "another.dev"},
            headers=admin_headers,
        )

    assert resp1.status_code == 201
    assert resp1.json()["domain"] == "bigalan.dev"
    assert resp2.status_code == 201
    assert resp2.json()["domain"] == "another.dev"


@pytest.mark.asyncio
async def test_check_slug_respects_domain(client, admin_headers):
    """GET /subdomains/check uses the domain param when checking availability."""
    import json
    from unittest.mock import patch

    from api.config import settings

    two_domains_json = json.dumps([
        {"domain": "bigalan.dev", "cloudflare_zone_id": ""},
        {"domain": "another.dev", "cloudflare_zone_id": ""},
    ])
    user_id = await _setup_user_with_credits(client, admin_headers, "checkdom@example.com", 2)

    with patch.object(settings, "domains", two_domains_json):
        await client.post(
            "/subdomains/purchase",
            json={"user_id": user_id, "slug": "domcheck", "domain": "bigalan.dev"},
            headers=admin_headers,
        )

        # Taken on bigalan.dev
        r1 = await client.get("/subdomains/check?slug=domcheck&domain=bigalan.dev")
        assert r1.status_code == 200
        assert r1.json()["available"] is False
        assert r1.json()["domain"] == "bigalan.dev"

        # Still available on another.dev
        r2 = await client.get("/subdomains/check?slug=domcheck&domain=another.dev")
        assert r2.status_code == 200
        assert r2.json()["available"] is True
        assert r2.json()["domain"] == "another.dev"


@pytest.mark.asyncio
async def test_delete_subdomain_with_domain_param(client, admin_headers):
    """DELETE /subdomains/{slug}?domain=... deletes the correct record."""
    import json
    from unittest.mock import patch

    from api.config import settings

    two_domains_json = json.dumps([
        {"domain": "bigalan.dev", "cloudflare_zone_id": ""},
        {"domain": "another.dev", "cloudflare_zone_id": ""},
    ])
    user_id = await _setup_user_with_credits(client, admin_headers, "deldomain@example.com", 4)

    with patch.object(settings, "domains", two_domains_json):
        await client.post(
            "/subdomains/purchase",
            json={"user_id": user_id, "slug": "delslug", "domain": "bigalan.dev"},
            headers=admin_headers,
        )
        await client.post(
            "/subdomains/purchase",
            json={"user_id": user_id, "slug": "delslug", "domain": "another.dev"},
            headers=admin_headers,
        )

        # Delete only the bigalan.dev one
        resp = await client.delete("/subdomains/delslug?domain=bigalan.dev", headers=admin_headers)
        assert resp.status_code == 204

        # another.dev version still exists
        check = await client.get("/subdomains/check?slug=delslug&domain=another.dev")
        assert check.json()["available"] is False
