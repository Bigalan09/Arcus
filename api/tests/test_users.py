"""Tests for POST /users."""

import pytest


@pytest.mark.asyncio
async def test_create_user_success(client, admin_headers):
    """Creating a user with a valid e-mail returns 201 with the user object."""
    resp = await client.post("/users", json={"email": "alice@example.com"}, headers=admin_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_user_duplicate_email(client, admin_headers):
    """Creating two users with the same e-mail returns 409 on the second."""
    await client.post("/users", json={"email": "bob@example.com"}, headers=admin_headers)
    resp = await client.post("/users", json={"email": "bob@example.com"}, headers=admin_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_user_invalid_email(client, admin_headers):
    """An invalid e-mail returns 422."""
    resp = await client.post("/users", json={"email": "not-an-email"}, headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_health_check(client):
    """GET /health returns 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
