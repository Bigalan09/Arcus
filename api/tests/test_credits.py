"""Tests for POST /credits/grant."""

import uuid

import pytest


async def _create_user(client, admin_headers, email="credituser@example.com"):
    resp = await client.post("/users", json={"email": email}, headers=admin_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_grant_credits_success(client, admin_headers):
    """Granting credits to an existing user returns 200 with updated balance."""
    user_id = await _create_user(client, admin_headers)
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": 5}, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 5
    assert data["user_id"] == user_id


@pytest.mark.asyncio
async def test_grant_credits_accumulates(client, admin_headers):
    """Granting credits multiple times accumulates correctly."""
    user_id = await _create_user(client, admin_headers)
    await client.post("/credits/grant", json={"user_id": user_id, "amount": 3}, headers=admin_headers)
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": 2}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["balance"] == 5


@pytest.mark.asyncio
async def test_grant_credits_unknown_user(client, admin_headers):
    """Granting credits to a non-existent user returns 404."""
    resp = await client.post(
        "/credits/grant",
        json={"user_id": str(uuid.uuid4()), "amount": 1},
        headers=admin_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_grant_credits_zero_amount(client, admin_headers):
    """Granting zero credits returns 422."""
    user_id = await _create_user(client, admin_headers)
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": 0}, headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_grant_credits_negative_amount(client, admin_headers):
    """Granting a negative number of credits returns 422."""
    user_id = await _create_user(client, admin_headers)
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": -3}, headers=admin_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_grant_credits_to_admin_rejected(client, admin_headers):
    """Admin accounts do not accept credits."""
    me = await client.get("/auth/me", headers=admin_headers)
    assert me.status_code == 200
    resp = await client.post(
        "/credits/grant",
        json={"user_id": me.json()["id"], "amount": 5},
        headers=admin_headers,
    )
    assert resp.status_code == 400
