"""Tests for user roles."""

import pytest


@pytest.mark.asyncio
async def test_create_user_default_role_is_normal(client, admin_headers):
    """A user created without an explicit role defaults to 'normal'."""
    resp = await client.post("/users", json={"email": "normal@example.com"}, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.json()["role"] == "normal"


@pytest.mark.asyncio
async def test_create_user_with_pro_role(client, admin_headers):
    """A user can be created with the 'pro' role."""
    resp = await client.post("/users", json={"email": "pro@example.com", "role": "pro"}, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.json()["role"] == "pro"


@pytest.mark.asyncio
async def test_create_second_admin_returns_409(client, admin_headers):
    """Creating a second admin returns 409 (only one admin is permitted)."""
    resp = await client.post("/users", json={"email": "admin2@example.com", "role": "admin"}, headers=admin_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_invalid_role_rejected(client, admin_headers):
    """An unrecognised role value returns 422."""
    resp = await client.post("/users", json={"email": "x@example.com", "role": "superuser"}, headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_role_present_in_response(client, admin_headers):
    """The role field is always present in UserResponse."""
    resp = await client.post("/users", json={"email": "r@example.com"}, headers=admin_headers)
    assert "role" in resp.json()
