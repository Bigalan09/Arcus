"""RED tests for user roles – fail until role is added to User model/route."""

import pytest


@pytest.mark.asyncio
async def test_create_user_default_role_is_normal(client):
    """A user created without an explicit role defaults to 'normal'."""
    resp = await client.post("/users", json={"email": "normal@example.com"})
    assert resp.status_code == 201
    assert resp.json()["role"] == "normal"


@pytest.mark.asyncio
async def test_create_user_with_pro_role(client):
    """A user can be created with the 'pro' role."""
    resp = await client.post("/users", json={"email": "pro@example.com", "role": "pro"})
    assert resp.status_code == 201
    assert resp.json()["role"] == "pro"


@pytest.mark.asyncio
async def test_create_user_with_admin_role(client):
    """The first admin can be created successfully."""
    resp = await client.post("/users", json={"email": "admin@example.com", "role": "admin"})
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_single_admin_constraint(client):
    """Creating a second admin returns 409."""
    await client.post("/users", json={"email": "admin1@example.com", "role": "admin"})
    resp = await client.post("/users", json={"email": "admin2@example.com", "role": "admin"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_invalid_role_rejected(client):
    """An unrecognised role value returns 422."""
    resp = await client.post("/users", json={"email": "x@example.com", "role": "superuser"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_role_present_in_response(client):
    """The role field is always present in UserResponse."""
    resp = await client.post("/users", json={"email": "r@example.com"})
    assert "role" in resp.json()
