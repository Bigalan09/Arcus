"""Docker-based end-to-end tests for the Arcus API.

These tests run against a real API server (and real PostgreSQL) deployed via
docker-compose.e2e.yml.  They exercise the same scenarios as the ASGI-layer
e2e suite but through actual HTTP, giving higher confidence that the full
production stack works correctly.

Usage (via Docker Compose):
    docker compose -f docker-compose.e2e.yml up --build --abort-on-container-exit

Usage (local, pointing at a running server):
    API_URL=http://localhost:8000 pytest e2e/ -v
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid

import httpx
import pytest
import pytest_asyncio

API_URL = os.environ.get("API_URL", "http://localhost:8000")

ADMIN_EMAIL = "e2e-admin@arcus.example.com"
ADMIN_PASSWORD = "AdminDockerPass1!"
NORMAL_EMAIL = "e2e-normal@arcus.example.com"
NORMAL_PASSWORD = "NormalDockerPass1!"
PRO_EMAIL = "e2e-pro@arcus.example.com"
PRO_PASSWORD = "ProDockerPass1!"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def http():
    """Yield an async HTTP client bound to the running API."""
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        yield client


@pytest_asyncio.fixture
async def admin_headers(http):
    """Bootstrap the admin account (idempotent) and return auth headers."""
    # Setup may have already been run; ignore 409
    await http.post("/auth/setup", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    login = await http.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_health(http):
    """GET /health returns 200 from the live server."""
    r = await http.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_login_success(http, admin_headers):
    """Admin can log in and receives a JWT."""
    r = await http.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    assert "access_token" in r.json()


@pytest.mark.asyncio
async def test_docker_login_wrong_password(http):
    """Wrong password returns 401."""
    r = await http.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "wrongpassword"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_docker_me(http, admin_headers):
    """GET /auth/me returns the authenticated user."""
    r = await http.get("/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_docker_cookie_reauth_after_logout(http):
    """The live server allows login, logout, and login again with the same client cookie jar."""
    await http.post("/auth/setup", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})

    login_1 = await http.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert login_1.status_code == 200
    assert http.cookies.get("arcus_session")

    me_1 = await http.get("/auth/me")
    assert me_1.status_code == 200

    logout = await http.post("/auth/logout")
    assert logout.status_code == 204
    assert http.cookies.get("arcus_session") is None

    me_2 = await http.get("/auth/me")
    assert me_2.status_code == 401

    login_2 = await http.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert login_2.status_code == 200
    assert http.cookies.get("arcus_session")

    me_3 = await http.get("/auth/me")
    assert me_3.status_code == 200


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_create_normal_user(http, admin_headers):
    """Admin can create a normal user."""
    email = f"normal-{uuid.uuid4().hex[:8]}@arcus.example.com"
    r = await http.post("/admin/users", json={"email": email, "role": "normal"}, headers=admin_headers)
    assert r.status_code == 201
    assert r.json()["role"] == "normal"
    assert r.json()["must_change_password"] is True


@pytest.mark.asyncio
async def test_docker_create_pro_user(http, admin_headers):
    """Admin can create a pro user."""
    email = f"pro-{uuid.uuid4().hex[:8]}@arcus.example.com"
    r = await http.post("/admin/users", json={"email": email, "role": "pro"}, headers=admin_headers)
    assert r.status_code == 201
    assert r.json()["role"] == "pro"


@pytest.mark.asyncio
async def test_docker_list_users(http, admin_headers):
    """GET /admin/users returns a non-empty list that includes the admin."""
    r = await http.get("/admin/users", headers=admin_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert any(u["email"] == ADMIN_EMAIL for u in r.json())


@pytest.mark.asyncio
async def test_docker_second_admin_rejected(http, admin_headers):
    """Creating a second admin user returns 409."""
    r = await http.post(
        "/admin/users",
        json={"email": "admin2@arcus.example.com", "role": "admin"},
        headers=admin_headers,
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_grant_and_get_credits(http, admin_headers):
    """Admin can grant credits; balance is reflected in GET /credits."""
    email = f"credit-{uuid.uuid4().hex[:8]}@arcus.example.com"
    create_r = await http.post("/admin/users", json={"email": email, "role": "normal"}, headers=admin_headers)
    user_id = create_r.json()["id"]

    grant_r = await http.post("/credits/grant", json={"user_id": user_id, "amount": 5}, headers=admin_headers)
    assert grant_r.status_code == 200
    assert grant_r.json()["balance"] == 5

    get_r = await http.get(f"/credits?user_id={user_id}", headers=admin_headers)
    assert get_r.status_code == 200
    assert get_r.json()["balance"] == 5


# ---------------------------------------------------------------------------
# Subdomains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_purchase_and_set_origin(http, admin_headers):
    """Admin can purchase a subdomain and set its origin."""
    email = f"sub-{uuid.uuid4().hex[:8]}@arcus.example.com"
    create_r = await http.post("/admin/users", json={"email": email, "role": "normal"}, headers=admin_headers)
    user_id = create_r.json()["id"]

    await http.post("/credits/grant", json={"user_id": user_id, "amount": 2}, headers=admin_headers)

    slug = f"e2e{uuid.uuid4().hex[:8]}"
    purch_r = await http.post(
        "/subdomains/purchase",
        json={"user_id": user_id, "slug": slug},
        headers=admin_headers,
    )
    assert purch_r.status_code == 201

    origin_r = await http.post(
        f"/subdomains/{slug}/origin",
        json={"origin_host": "203.0.113.42", "origin_port": 8080},
        headers=admin_headers,
    )
    assert origin_r.status_code == 200
    assert origin_r.json()["origin_host"] == "203.0.113.42"


@pytest.mark.asyncio
async def test_docker_subdomain_check(http):
    """GET /subdomains/check is public and returns availability."""
    r = await http.get("/subdomains/check?slug=definitelyunused9999")
    assert r.status_code == 200
    assert r.json()["available"] is True


# ---------------------------------------------------------------------------
# Blocklist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_blocklist_crud(http, admin_headers):
    """Admin can add, list, and remove blocklist words."""
    word = f"testword{uuid.uuid4().hex[:6]}"

    add_r = await http.post("/admin/blocklist", json={"words": [word]}, headers=admin_headers)
    assert add_r.status_code == 201

    list_r = await http.get("/admin/blocklist", headers=admin_headers)
    assert any(e["word"] == word for e in list_r.json())

    del_r = await http.delete(f"/admin/blocklist/{word}", headers=admin_headers)
    assert del_r.status_code == 204


# ---------------------------------------------------------------------------
# System webhooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_system_webhook_crud(http, admin_headers):
    """Admin can create, update, and delete system webhooks."""
    create_r = await http.post(
        "/admin/webhooks",
        json={"url": "https://hook.example.com/sys", "events": ["credit.request"], "active": True},
        headers=admin_headers,
    )
    assert create_r.status_code == 201
    wh_id = create_r.json()["id"]

    update_r = await http.put(
        f"/admin/webhooks/{wh_id}",
        json={"active": False},
        headers=admin_headers,
    )
    assert update_r.status_code == 200
    assert update_r.json()["active"] is False

    del_r = await http.delete(f"/admin/webhooks/{wh_id}", headers=admin_headers)
    assert del_r.status_code == 204


# ---------------------------------------------------------------------------
# API tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_api_token_lifecycle(http, admin_headers):
    """Admin can create, list, use, and revoke an API token."""
    create_r = await http.post("/tokens", json={"name": "docker-e2e-key"}, headers=admin_headers)
    assert create_r.status_code == 201
    raw_token = create_r.json()["token"]
    token_id = create_r.json()["id"]
    assert raw_token.startswith("arc_")

    # Use the token
    me_r = await http.get("/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
    assert me_r.status_code == 200

    # List shows it (without raw value)
    list_r = await http.get("/tokens", headers=admin_headers)
    assert any(t["id"] == token_id for t in list_r.json())
    assert all("token" not in t for t in list_r.json())

    # Revoke
    del_r = await http.delete(f"/tokens/{token_id}", headers=admin_headers)
    assert del_r.status_code == 204

    # Token no longer works
    revoked_r = await http.get("/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
    assert revoked_r.status_code == 401


# ---------------------------------------------------------------------------
# Role access control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docker_unauthenticated_returns_401(http):
    """Protected endpoints return 401 without credentials."""
    r = await http.get("/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_docker_unauthenticated_returns_401(http):
    """Protected endpoints return 401 without credentials."""
    protected = [
        ("GET", "/auth/me"),
        ("GET", "/credits"),
        ("GET", "/admin/users"),
        ("GET", "/admin/webhooks"),
        ("GET", "/admin/blocklist"),
        ("GET", "/webhooks"),
    ]
    for method, path in protected:
        r = await getattr(http, method.lower())(path)
        assert r.status_code == 401, f"{method} {path} should be 401, got {r.status_code}"
