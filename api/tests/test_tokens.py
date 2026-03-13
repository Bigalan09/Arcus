"""Tests for API token management endpoints."""

from datetime import UTC, datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# Create token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_token_success(client, admin_headers):
    """POST /tokens creates a new API token and returns it once."""
    resp = await client.post("/tokens", json={"name": "my-token"}, headers=admin_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "my-token"
    assert "token" in data
    assert data["token"].startswith("arc_")
    assert "id" in data


@pytest.mark.asyncio
async def test_create_token_requires_auth(client):
    """POST /tokens without auth returns 401."""
    resp = await client.post("/tokens", json={"name": "my-token"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tokens_empty(client, admin_headers):
    """GET /tokens returns empty list when no tokens exist."""
    resp = await client.get("/tokens", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_tokens_shows_created(client, admin_headers):
    """GET /tokens lists tokens after creation."""
    await client.post("/tokens", json={"name": "token-a"}, headers=admin_headers)
    await client.post("/tokens", json={"name": "token-b"}, headers=admin_headers)

    resp = await client.get("/tokens", headers=admin_headers)
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert "token-a" in names
    assert "token-b" in names


@pytest.mark.asyncio
async def test_list_tokens_no_raw_value(client, admin_headers):
    """GET /tokens does not include the raw token value."""
    await client.post("/tokens", json={"name": "safe-token"}, headers=admin_headers)
    resp = await client.get("/tokens", headers=admin_headers)
    for token in resp.json():
        assert "token" not in token


# ---------------------------------------------------------------------------
# Token limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_create_unlimited_tokens(client, admin_headers):
    """Admin users are not subject to a token limit."""
    for i in range(10):
        resp = await client.post("/tokens", json={"name": f"t{i}"}, headers=admin_headers)
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_normal_user_limited_to_one_token(client, admin_headers):
    """Normal users can create only 1 token; the second returns 409."""
    # Create a normal user via admin
    user_resp = await client.post("/admin/users", json={"email": "normal@example.com", "role": "normal"}, headers=admin_headers)
    user_email = user_resp.json()["email"]
    user_id = user_resp.json()["id"]

    # Set a known password directly in the test DB
    import uuid

    from sqlalchemy import select

    from api.models import User
    from api.tests.conftest import TestSessionLocal
    from api.utils.auth import hash_password

    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
        u = result.scalar_one()
        u.password_hash = hash_password("UserPass123!")
        u.must_change_password = False
        await session.commit()

    # Login as normal user
    login_resp = await client.post("/auth/login", json={"email": user_email, "password": "UserPass123!"})
    assert login_resp.status_code == 200
    user_jwt_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    # First token succeeds
    r1 = await client.post("/tokens", json={"name": "t1"}, headers=user_jwt_headers)
    assert r1.status_code == 201

    # Second token fails
    r2 = await client.post("/tokens", json={"name": "t2"}, headers=user_jwt_headers)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Delete token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_token_success(client, admin_headers):
    """DELETE /tokens/{id} removes the token."""
    create_resp = await client.post("/tokens", json={"name": "to-revoke"}, headers=admin_headers)
    token_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/tokens/{token_id}", headers=admin_headers)
    assert del_resp.status_code == 204

    # Verify it's gone from the list
    list_resp = await client.get("/tokens", headers=admin_headers)
    ids = [t["id"] for t in list_resp.json()]
    assert token_id not in ids


@pytest.mark.asyncio
async def test_revoke_nonexistent_token_returns_404(client, admin_headers):
    """DELETE /tokens/{id} for unknown ID returns 404."""
    import uuid
    resp = await client.delete(f"/tokens/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API token authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_token_authenticates_requests(client, admin_headers):
    """An API token can be used as a Bearer token to authenticate requests."""
    create_resp = await client.post("/tokens", json={"name": "api-key"}, headers=admin_headers)
    raw_token = create_resp.json()["token"]

    # Use the API token to call an authenticated endpoint
    api_headers = {"Authorization": f"Bearer {raw_token}"}
    me_resp = await client.get("/auth/me", headers=api_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_expired_api_token_is_rejected(client, admin_headers):
    """API tokens older than 90 days cannot authenticate."""
    create_resp = await client.post("/tokens", json={"name": "expiring-key"}, headers=admin_headers)
    assert create_resp.status_code == 201
    raw_token = create_resp.json()["token"]
    token_id = create_resp.json()["id"]

    import uuid

    from sqlalchemy import select

    from api.models import ApiToken
    from api.tests.conftest import TestSessionLocal

    async with TestSessionLocal() as session:
        result = await session.execute(select(ApiToken).where(ApiToken.id == uuid.UUID(token_id)))
        tok = result.scalar_one()
        tok.created_at = datetime.now(UTC) - timedelta(days=91)
        await session.commit()

    api_headers = {"Authorization": f"Bearer {raw_token}"}
    me_resp = await client.get("/auth/me", headers=api_headers)
    assert me_resp.status_code == 401
