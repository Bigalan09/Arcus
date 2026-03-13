"""Tests for authentication endpoints: setup, login, change-password, me."""

import pytest

# ---------------------------------------------------------------------------
# /auth/setup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_succeeds_when_no_admin(client):
    """POST /auth/setup creates the first admin and returns 201."""
    resp = await client.post(
        "/auth/setup",
        json={"email": "admin@example.com", "password": "setuptest12"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "admin@example.com"
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_setup_fails_if_admin_exists(client):
    """POST /auth/setup fails with 409 if admin already exists."""
    await client.post("/auth/setup", json={"email": "admin@example.com", "password": "setuptest12"})
    resp = await client.post(
        "/auth/setup",
        json={"email": "admin2@example.com", "password": "setuptest12"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_setup_check_needed(client):
    """GET /auth/setup-status returns needed=true when no admin exists."""
    resp = await client.get("/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needed"] is True


@pytest.mark.asyncio
async def test_setup_check_not_needed_after_creation(client):
    """GET /auth/setup-status returns needed=false after admin is created."""
    await client.post("/auth/setup", json={"email": "admin@example.com", "password": "setuptest12"})
    resp = await client.get("/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["needed"] is False


# ---------------------------------------------------------------------------
# /auth/login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(client):
    """POST /auth/login with valid credentials returns access_token."""
    await client.post("/auth/setup", json={"email": "admin@example.com", "password": "setuptest12"})
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "setuptest12"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["must_change_password"] is False


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    """POST /auth/login with wrong password returns 401."""
    await client.post("/auth/setup", json={"email": "admin@example.com", "password": "setuptest12"})
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    """POST /auth/login with unknown email returns 401."""
    resp = await client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_returns_current_user(client, admin_token):
    """GET /auth/me returns the authenticated user."""
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    """GET /auth/me without auth returns 401."""
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/change-password
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_success(client, admin_token):
    """POST /auth/change-password with correct current password succeeds."""
    resp = await client.post(
        "/auth/change-password",
        json={"current_password": "testadmin12", "new_password": "newpassword99"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_change_password_wrong_current(client, admin_token):
    """POST /auth/change-password with wrong current password returns 401."""
    resp = await client.post(
        "/auth/change-password",
        json={"current_password": "wrongpassword", "new_password": "newpassword99"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_password_same_password(client, admin_token):
    """POST /auth/change-password with the same new password returns 400."""
    resp = await client.post(
        "/auth/change-password",
        json={"current_password": "testadmin12", "new_password": "testadmin12"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_change_password_too_short(client, admin_token):
    """POST /auth/change-password with a short new password returns 422."""
    resp = await client.post(
        "/auth/change-password",
        json={"current_password": "testadmin12", "new_password": "short"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422
