"""Tests for GET /credits and POST /credits/request."""

import uuid

import pytest


async def _create_user(client, email="creditrequser@example.com"):
    resp = await client.post("/users", json={"email": email})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _grant_credits(client, user_id, amount=5):
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": amount})
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# GET /credits?user_id=...
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_credits_returns_balance(client):
    """GET /credits?user_id=... returns the current credit balance."""
    user_id = await _create_user(client)
    await _grant_credits(client, user_id, amount=7)

    resp = await client.get(f"/credits?user_id={user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 7
    assert data["user_id"] == user_id


@pytest.mark.asyncio
async def test_get_credits_unknown_user(client):
    """GET /credits for an unknown user returns 404."""
    resp = await client.get(f"/credits?user_id={uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_credits_new_user_has_zero_balance(client):
    """GET /credits for a newly created user returns balance 0."""
    user_id = await _create_user(client, "nocredit@example.com")
    resp = await client.get(f"/credits?user_id={user_id}")
    assert resp.status_code == 200
    assert resp.json()["balance"] == 0


@pytest.mark.asyncio
async def test_get_credits_after_multiple_grants(client):
    """GET /credits reflects accumulated balance after multiple grants."""
    user_id = await _create_user(client, "multi@example.com")
    await _grant_credits(client, user_id, amount=3)
    await _grant_credits(client, user_id, amount=4)

    resp = await client.get(f"/credits?user_id={user_id}")
    assert resp.status_code == 200
    assert resp.json()["balance"] == 7


# ---------------------------------------------------------------------------
# POST /credits/request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_credits_success_no_webhooks(client):
    """POST /credits/request returns 202; zero webhooks fired when none registered."""
    user_id = await _create_user(client, "requser@example.com")

    resp = await client.post("/credits/request", json={"user_id": user_id})
    assert resp.status_code == 202
    data = resp.json()
    assert data["user_id"] == user_id
    assert data["webhooks_fired"] == 0


@pytest.mark.asyncio
async def test_request_credits_with_message(client):
    """POST /credits/request accepts an optional message field."""
    user_id = await _create_user(client, "reqmsg@example.com")

    resp = await client.post(
        "/credits/request",
        json={"user_id": user_id, "message": "Need credits for project X"},
    )
    assert resp.status_code == 202
    assert resp.json()["user_id"] == user_id


@pytest.mark.asyncio
async def test_request_credits_unknown_user(client):
    """POST /credits/request for a non-existent user returns 404."""
    resp = await client.post("/credits/request", json={"user_id": str(uuid.uuid4())})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_request_credits_message_too_long(client):
    """POST /credits/request with a message over 500 chars returns 422."""
    user_id = await _create_user(client, "longmsg@example.com")
    resp = await client.post(
        "/credits/request",
        json={"user_id": user_id, "message": "x" * 501},
    )
    assert resp.status_code == 422
