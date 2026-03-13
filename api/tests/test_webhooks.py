"""Tests for admin webhook CRUD endpoints."""

import os
import uuid

import pytest

API_KEY = os.environ.get("API_SECRET_KEY", "changeme")
HEADERS = {"X-Api-Key": API_KEY}

SAMPLE_WEBHOOK = {
    "url": "https://example.com/webhook",
    "events": ["credit.request"],
    "active": True,
}


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_webhooks_requires_api_key(client):
    """GET /admin/webhooks without API key returns 401."""
    resp = await client.get("/admin/webhooks")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_webhook_requires_api_key(client):
    """POST /admin/webhooks without API key returns 401."""
    resp = await client.post("/admin/webhooks", json=SAMPLE_WEBHOOK)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_webhooks_empty(client):
    """GET /admin/webhooks returns an empty list when no webhooks exist."""
    resp = await client.get("/admin/webhooks", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_webhook_success(client):
    """POST /admin/webhooks creates and returns the new webhook."""
    resp = await client.post("/admin/webhooks", json=SAMPLE_WEBHOOK, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://example.com/webhook"
    assert "credit.request" in data["events"]
    assert data["active"] is True
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_webhook_with_secret(client):
    """POST /admin/webhooks with a secret stores it but does not expose it in response."""
    payload = {**SAMPLE_WEBHOOK, "secret": "mysecret123"}
    resp = await client.post("/admin/webhooks", json=payload, headers=HEADERS)
    assert resp.status_code == 201
    # Secret must NOT appear in the response for security.
    assert "secret" not in resp.json()


@pytest.mark.asyncio
async def test_create_webhook_multiple_events(client):
    """POST /admin/webhooks with multiple events stores them all."""
    payload = {**SAMPLE_WEBHOOK, "events": ["credit.request", "user.created"]}
    resp = await client.post("/admin/webhooks", json=payload, headers=HEADERS)
    assert resp.status_code == 201
    events = resp.json()["events"]
    assert "credit.request" in events
    assert "user.created" in events


@pytest.mark.asyncio
async def test_create_webhook_inactive(client):
    """POST /admin/webhooks with active=False creates an inactive webhook."""
    payload = {**SAMPLE_WEBHOOK, "active": False}
    resp = await client.post("/admin/webhooks", json=payload, headers=HEADERS)
    assert resp.status_code == 201
    assert resp.json()["active"] is False


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_webhook_success(client):
    """GET /admin/webhooks/{id} returns the correct webhook."""
    create_resp = await client.post("/admin/webhooks", json=SAMPLE_WEBHOOK, headers=HEADERS)
    webhook_id = create_resp.json()["id"]

    resp = await client.get(f"/admin/webhooks/{webhook_id}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["id"] == webhook_id


@pytest.mark.asyncio
async def test_get_webhook_not_found(client):
    """GET /admin/webhooks/{id} with unknown ID returns 404."""
    resp = await client.get(f"/admin/webhooks/{uuid.uuid4()}", headers=HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_webhook_url(client):
    """PUT /admin/webhooks/{id} updates the URL."""
    create_resp = await client.post("/admin/webhooks", json=SAMPLE_WEBHOOK, headers=HEADERS)
    webhook_id = create_resp.json()["id"]

    resp = await client.put(
        f"/admin/webhooks/{webhook_id}",
        json={"url": "https://new.example.com/hook"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://new.example.com/hook"


@pytest.mark.asyncio
async def test_update_webhook_deactivate(client):
    """PUT /admin/webhooks/{id} can deactivate a webhook."""
    create_resp = await client.post("/admin/webhooks", json=SAMPLE_WEBHOOK, headers=HEADERS)
    webhook_id = create_resp.json()["id"]

    resp = await client.put(
        f"/admin/webhooks/{webhook_id}",
        json={"active": False},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False


@pytest.mark.asyncio
async def test_update_webhook_events(client):
    """PUT /admin/webhooks/{id} can update the subscribed events."""
    create_resp = await client.post("/admin/webhooks", json=SAMPLE_WEBHOOK, headers=HEADERS)
    webhook_id = create_resp.json()["id"]

    resp = await client.put(
        f"/admin/webhooks/{webhook_id}",
        json={"events": ["user.created"]},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["events"] == ["user.created"]


@pytest.mark.asyncio
async def test_update_webhook_not_found(client):
    """PUT /admin/webhooks/{id} with unknown ID returns 404."""
    resp = await client.put(
        f"/admin/webhooks/{uuid.uuid4()}",
        json={"active": False},
        headers=HEADERS,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_webhook_success(client):
    """DELETE /admin/webhooks/{id} removes the webhook and returns 204."""
    create_resp = await client.post("/admin/webhooks", json=SAMPLE_WEBHOOK, headers=HEADERS)
    webhook_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/admin/webhooks/{webhook_id}", headers=HEADERS)
    assert del_resp.status_code == 204

    # Verify it's gone.
    get_resp = await client.get(f"/admin/webhooks/{webhook_id}", headers=HEADERS)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_webhook_not_found(client):
    """DELETE /admin/webhooks/{id} with unknown ID returns 404."""
    resp = await client.delete(f"/admin/webhooks/{uuid.uuid4()}", headers=HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List after operations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_webhooks_shows_all(client):
    """GET /admin/webhooks lists all created webhooks."""
    await client.post(
        "/admin/webhooks",
        json={**SAMPLE_WEBHOOK, "url": "https://a.example.com/hook"},
        headers=HEADERS,
    )
    await client.post(
        "/admin/webhooks",
        json={**SAMPLE_WEBHOOK, "url": "https://b.example.com/hook"},
        headers=HEADERS,
    )

    resp = await client.get("/admin/webhooks", headers=HEADERS)
    assert resp.status_code == 200
    urls = [w["url"] for w in resp.json()]
    assert "https://a.example.com/hook" in urls
    assert "https://b.example.com/hook" in urls
