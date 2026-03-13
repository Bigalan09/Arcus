"""Tests for GET /credits and POST /credits/request."""

import uuid

import pytest


async def _create_user(client, admin_headers, email="creditrequser@example.com"):
    resp = await client.post("/users", json={"email": email}, headers=admin_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


async def _grant_credits(client, admin_headers, user_id, amount=5):
    resp = await client.post("/credits/grant", json={"user_id": user_id, "amount": amount}, headers=admin_headers)
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# GET /credits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_credits_returns_balance(client, admin_headers):
    """GET /credits?user_id=... (admin) returns the current credit balance."""
    user_id = await _create_user(client, admin_headers)
    await _grant_credits(client, admin_headers, user_id, amount=7)

    resp = await client.get(f"/credits?user_id={user_id}", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["balance"] == 7
    assert data["user_id"] == user_id


@pytest.mark.asyncio
async def test_get_credits_unknown_user(client, admin_headers):
    """GET /credits for an unknown user_id (admin) returns 404."""
    resp = await client.get(f"/credits?user_id={uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_credits_new_user_has_zero_balance(client, admin_headers):
    """GET /credits for a newly created user returns balance 0."""
    user_id = await _create_user(client, admin_headers, "nocredit@example.com")
    resp = await client.get(f"/credits?user_id={user_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["balance"] == 0


@pytest.mark.asyncio
async def test_get_credits_after_multiple_grants(client, admin_headers):
    """GET /credits reflects accumulated balance after multiple grants."""
    user_id = await _create_user(client, admin_headers, "multi@example.com")
    await _grant_credits(client, admin_headers, user_id, amount=3)
    await _grant_credits(client, admin_headers, user_id, amount=4)

    resp = await client.get(f"/credits?user_id={user_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["balance"] == 7


@pytest.mark.asyncio
async def test_get_credits_admin_account_rejected(client, admin_headers):
    """GET /credits is not available for admin accounts."""
    resp = await client.get("/credits", headers=admin_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /credits/request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_credits_success_no_webhooks(client, normal_user):
    """POST /credits/request returns 202 for a normal user requesting their own credits."""
    resp = await client.post(
        "/credits/request",
        json={"user_id": normal_user["id"], "amount": 5},
        headers=normal_user["headers"],
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["user_id"] == normal_user["id"]
    assert data["webhooks_fired"] == 0


@pytest.mark.asyncio
async def test_request_credits_with_message(client, normal_user):
    """POST /credits/request accepts an optional message field."""
    resp = await client.post(
        "/credits/request",
        json={"user_id": normal_user["id"], "amount": 3, "message": "Need credits for project X"},
        headers=normal_user["headers"],
    )
    assert resp.status_code == 202
    assert resp.json()["user_id"] == normal_user["id"]


@pytest.mark.asyncio
async def test_request_credits_unknown_user(client, normal_user):
    """POST /credits/request for a non-existent user returns 404."""
    resp = await client.post(
        "/credits/request",
        json={"user_id": str(uuid.uuid4()), "amount": 1},
        headers=normal_user["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_request_credits_message_too_long(client, normal_user):
    """POST /credits/request with a message over 500 chars returns 422."""
    resp = await client.post(
        "/credits/request",
        json={"user_id": normal_user["id"], "amount": 1, "message": "x" * 501},
        headers=normal_user["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_request_credits_missing_amount(client, normal_user):
    """POST /credits/request without amount returns 422."""
    resp = await client.post(
        "/credits/request",
        json={"user_id": normal_user["id"]},
        headers=normal_user["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_request_credits_zero_amount(client, normal_user):
    """POST /credits/request with amount=0 returns 422."""
    resp = await client.post(
        "/credits/request",
        json={"user_id": normal_user["id"], "amount": 0},
        headers=normal_user["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_cannot_request_credits(client, admin_headers):
    """POST /credits/request is blocked for admin accounts."""
    me = await client.get("/auth/me", headers=admin_headers)
    assert me.status_code == 200
    admin_id = me.json()["id"]
    resp = await client.post(
        "/credits/request",
        json={"user_id": admin_id, "amount": 2},
        headers=admin_headers,
    )
    assert resp.status_code == 400
