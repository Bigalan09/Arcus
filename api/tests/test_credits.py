"""RED tests for POST /credits/grant – must fail until implemented."""

import pytest


async def _create_user(client, email="credituser@example.com"):
    resp = await client.post("/users", json={"email": email})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_grant_credits_success(client):
    """Granting credits to an existing user returns 200 with updated balance."""
    user_id = await _create_user(client)
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 5
    assert data["user_id"] == user_id


@pytest.mark.asyncio
async def test_grant_credits_accumulates(client):
    """Granting credits multiple times accumulates correctly."""
    user_id = await _create_user(client)
    await client.post("/credits/grant", json={"user_id": user_id, "amount": 3})
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": 2})
    assert resp.status_code == 200
    assert resp.json()["balance"] == 5


@pytest.mark.asyncio
async def test_grant_credits_unknown_user(client):
    """Granting credits to a non-existent user returns 404."""
    import uuid
    resp = await client.post(
        "/credits/grant",
        json={"user_id": str(uuid.uuid4()), "amount": 1},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_grant_credits_zero_amount(client):
    """Granting zero credits returns 422."""
    user_id = await _create_user(client)
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": 0})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_grant_credits_negative_amount(client):
    """Granting a negative number of credits returns 422."""
    user_id = await _create_user(client)
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": -3})
    assert resp.status_code == 422
