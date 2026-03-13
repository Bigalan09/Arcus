"""Comprehensive end-to-end test suite for the Arcus API.

Covers every role (normal, pro, admin), every webhook scenario, every API
endpoint and access-control rule.  Uses the same in-memory SQLite fixture as
the unit tests so no external services are required.

Scenarios
---------
1.  Admin journey              – setup, user management, credits, blocklist,
                                 system webhooks, subdomain management, password
                                 reset, GET /admin/users.
2.  Normal-user journey        – login (after forced password change), own credits,
                                 subdomains, single API-token limit, forbidden
                                 endpoints.
3.  Pro-user journey           – user webhooks CRUD, 5-token limit, forbidden
                                 admin endpoints.
4.  Webhook-delivery scenarios – system webhook fires, user webhook fires, HMAC
                                 signature, inactive webhook skipped, wrong-event
                                 webhook skipped.
5.  Role-access enforcement    – each role tested against every endpoint it must
                                 not reach.
6.  API-token authentication   – all three roles authenticating with arc_ tokens.
7.  Cookie authentication      – arcus_session cookie accepted as auth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from api.config import settings
from api.models import User
from api.tests.conftest import TestSessionLocal
from api.utils.auth import hash_password

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "e2e-admin@arcus.example.com"
ADMIN_PASSWORD = "testadmin12"
NORMAL_EMAIL = "e2e-normal@arcus.example.com"
NORMAL_PASSWORD = "testnorm12"
PRO_EMAIL = "e2e-pro@arcus.example.com"
PRO_PASSWORD = "testpro1234"


async def _setup_admin(client):
    """Bootstrap the admin account and return a Bearer-header dict."""
    resp = await client.post(
        "/auth/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post(
        "/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_user_with_password(
    client,
    admin_headers: dict,
    email: str,
    role: str = "normal",
    password: str = "testuser12",
) -> dict:
    """Create a user via /admin/users and inject a known password directly.

    Returns a dict with keys: ``id``, ``email``, ``role``, ``headers``.
    """
    resp = await client.post(
        "/admin/users",
        json={"email": email, "role": role},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user_obj = result.scalar_one()
        user_obj.password_hash = hash_password(password)
        user_obj.must_change_password = False
        await session.commit()

    login = await client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {
        "id": user_id,
        "email": email,
        "role": role,
        "headers": {"Authorization": f"Bearer {token}"},
        "token": token,
    }


# ===========================================================================
# 1. Admin journey
# ===========================================================================


@pytest.mark.asyncio
async def test_admin_full_journey(client):
    """Full admin journey: setup → users → credits → blocklist → webhooks."""
    admin_headers = await _setup_admin(client)

    # --- create normal and pro users ---
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    # --- list users ---
    r = await client.get("/admin/users", headers=admin_headers)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert ADMIN_EMAIL in emails
    assert NORMAL_EMAIL in emails
    assert PRO_EMAIL in emails

    # --- grant credits ---
    r = await client.post(
        "/credits/grant",
        json={"user_id": normal["id"], "amount": 10},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["balance"] == 10

    # --- admin can query any user's credits ---
    r = await client.get(f"/credits?user_id={normal['id']}", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["balance"] == 10

    # --- admin purchases subdomain on behalf of normal user ---
    r = await client.post(
        "/subdomains/purchase",
        json={"user_id": normal["id"], "slug": "adminbuy"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["slug"] == "adminbuy"

    # --- admin can list any user's subdomains ---
    r = await client.get(f"/subdomains?user_id={normal['id']}", headers=admin_headers)
    assert r.status_code == 200
    slugs = [s["slug"] for s in r.json()]
    assert "adminbuy" in slugs

    # --- admin can set origin on another user's subdomain ---
    r = await client.post(
        "/subdomains/adminbuy/origin",
        json={"origin_host": "203.0.113.5", "origin_port": 8080},
        headers=admin_headers,
    )
    assert r.status_code == 200

    # --- blocklist: add, check, delete ---
    r = await client.post(
        "/admin/blocklist",
        json={"words": ["e2eblocked"]},
        headers=admin_headers,
    )
    assert r.status_code == 201
    r = await client.get("/admin/blocklist", headers=admin_headers)
    assert any(e["word"] == "e2eblocked" for e in r.json())
    r = await client.delete("/admin/blocklist/e2eblocked", headers=admin_headers)
    assert r.status_code == 204

    # --- system webhook: create, list, update, delete ---
    r = await client.post(
        "/admin/webhooks",
        json={"url": "https://hooks.example.com/sys", "events": ["credit.request"], "active": True},
        headers=admin_headers,
    )
    assert r.status_code == 201
    webhook_id = r.json()["id"]

    r = await client.get("/admin/webhooks", headers=admin_headers)
    assert r.status_code == 200
    assert any(w["id"] == webhook_id for w in r.json())

    r = await client.put(
        f"/admin/webhooks/{webhook_id}",
        json={"active": False},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["active"] is False

    r = await client.delete(f"/admin/webhooks/{webhook_id}", headers=admin_headers)
    assert r.status_code == 204

    # --- reset user password ---
    r = await client.post(f"/admin/users/{normal['id']}/reset-password", headers=admin_headers)
    assert r.status_code == 204

    # verify must_change_password is now True after reset
    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == uuid.UUID(normal["id"])))
        u = result.scalar_one()
        assert u.must_change_password is True

    # --- health check ---
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ===========================================================================
# 2. Normal-user journey
# ===========================================================================


@pytest.mark.asyncio
async def test_normal_user_full_journey(client):
    """Full normal-user journey: login, credits, subdomains, tokens, access control."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    nh = normal["headers"]

    # grant credits so the user can buy subdomains
    await client.post(
        "/credits/grant",
        json={"user_id": normal["id"], "amount": 3},
        headers=admin_headers,
    )

    # --- view own credits ---
    r = await client.get("/credits", headers=nh)
    assert r.status_code == 200
    assert r.json()["balance"] == 3

    # --- purchase subdomain for self ---
    r = await client.post(
        "/subdomains/purchase",
        json={"user_id": normal["id"], "slug": "myapp"},
        headers=nh,
    )
    assert r.status_code == 201
    assert r.json()["slug"] == "myapp"

    # credit decremented
    r = await client.get("/credits", headers=nh)
    assert r.json()["balance"] == 2

    # --- set origin ---
    r = await client.post(
        "/subdomains/myapp/origin",
        json={"origin_host": "198.51.100.1", "origin_port": 3000},
        headers=nh,
    )
    assert r.status_code == 200
    assert r.json()["origin_host"] == "198.51.100.1"

    # --- list own subdomains ---
    r = await client.get("/subdomains", headers=nh)
    assert r.status_code == 200
    assert any(s["slug"] == "myapp" for s in r.json())

    # --- request credits ---
    r = await client.post(
        "/credits/request",
        json={"user_id": normal["id"], "amount": 5},
        headers=nh,
    )
    assert r.status_code == 202

    # --- create one API token ---
    r = await client.post("/tokens", json={"name": "my-key"}, headers=nh)
    assert r.status_code == 201
    assert r.json()["token"].startswith("arc_")

    # --- second token rejected (normal limit = 1) ---
    r = await client.post("/tokens", json={"name": "my-key-2"}, headers=nh)
    assert r.status_code == 409

    # --- /auth/me works ---
    r = await client.get("/auth/me", headers=nh)
    assert r.status_code == 200
    assert r.json()["role"] == "normal"


@pytest.mark.asyncio
async def test_normal_user_cannot_buy_for_other_user(client):
    """Normal user gets 403 when trying to purchase a subdomain for another user."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")
    await client.post(
        "/credits/grant",
        json={"user_id": normal["id"], "amount": 5},
        headers=admin_headers,
    )

    r = await client.post(
        "/subdomains/purchase",
        json={"user_id": pro["id"], "slug": "stolen"},
        headers=normal["headers"],
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_normal_user_cannot_query_other_credits(client):
    """Normal user gets 403 when querying another user's credit balance."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    r = await client.get(f"/credits?user_id={pro['id']}", headers=normal["headers"])
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_normal_user_cannot_request_credits_for_other_user(client):
    """Normal user gets 403 when requesting credits for another user."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    r = await client.post(
        "/credits/request",
        json={"user_id": pro["id"], "amount": 1},
        headers=normal["headers"],
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_normal_user_cannot_set_origin_on_other_subdomain(client):
    """Normal user gets 403 when trying to set origin on a subdomain they don't own."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    await client.post(
        "/credits/grant",
        json={"user_id": pro["id"], "amount": 2},
        headers=admin_headers,
    )
    # Pro user purchases a subdomain
    await client.post(
        "/subdomains/purchase",
        json={"user_id": pro["id"], "slug": "proapp"},
        headers=pro["headers"],
    )

    # Normal user tries to set origin on pro's subdomain
    r = await client.post(
        "/subdomains/proapp/origin",
        json={"origin_host": "203.0.113.99", "origin_port": 9000},
        headers=normal["headers"],
    )
    assert r.status_code == 403


# ===========================================================================
# 3. Pro-user journey
# ===========================================================================


@pytest.mark.asyncio
async def test_pro_user_full_journey(client):
    """Full pro-user journey: user webhooks CRUD and 5-token limit."""
    admin_headers = await _setup_admin(client)
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")
    ph = pro["headers"]

    # --- user webhooks: create ---
    r = await client.post(
        "/webhooks",
        json={"url": "https://myhook.example.com/events", "events": ["user.created"], "active": True},
        headers=ph,
    )
    assert r.status_code == 201
    wh_id = r.json()["id"]
    assert r.json()["active"] is True

    # --- user webhooks: list ---
    r = await client.get("/webhooks", headers=ph)
    assert r.status_code == 200
    assert any(w["id"] == wh_id for w in r.json())

    # --- user webhooks: update ---
    r = await client.put(
        f"/webhooks/{wh_id}",
        json={"url": "https://myhook.example.com/v2/events", "active": False},
        headers=ph,
    )
    assert r.status_code == 200
    assert r.json()["url"] == "https://myhook.example.com/v2/events"
    assert r.json()["active"] is False

    # --- user webhooks: delete ---
    r = await client.delete(f"/webhooks/{wh_id}", headers=ph)
    assert r.status_code == 204

    r = await client.get("/webhooks", headers=ph)
    assert r.status_code == 200
    assert not any(w["id"] == wh_id for w in r.json())

    # --- pro user: 5 tokens allowed ---
    for i in range(5):
        r = await client.post("/tokens", json={"name": f"pro-token-{i}"}, headers=ph)
        assert r.status_code == 201, f"token {i} failed: {r.text}"

    # 6th token rejected
    r = await client.post("/tokens", json={"name": "pro-token-overflow"}, headers=ph)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_pro_user_webhook_secret(client):
    """Pro user can create a webhook with a secret (secret not exposed in response)."""
    admin_headers = await _setup_admin(client)
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    r = await client.post(
        "/webhooks",
        json={
            "url": "https://signed.example.com/hook",
            "secret": "mysupersecretsigning",
            "events": ["user.created"],
            "active": True,
        },
        headers=pro["headers"],
    )
    assert r.status_code == 201
    assert "secret" not in r.json()


@pytest.mark.asyncio
async def test_pro_user_cannot_access_admin_endpoints(client):
    """Pro user is forbidden from every admin-only endpoint."""
    admin_headers = await _setup_admin(client)
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")
    ph = pro["headers"]

    assert (await client.get("/admin/users", headers=ph)).status_code == 403
    assert (await client.post("/admin/users", json={"email": "x@x.com"}, headers=ph)).status_code == 403
    assert (await client.get("/admin/webhooks", headers=ph)).status_code == 403
    assert (await client.post("/admin/webhooks", json={"url": "https://x.com", "events": []}, headers=ph)).status_code == 403
    assert (await client.get("/admin/blocklist", headers=ph)).status_code == 403
    assert (await client.post("/admin/blocklist", json={"words": ["x"]}, headers=ph)).status_code == 403
    assert (
        await client.post("/credits/grant", json={"user_id": str(uuid.uuid4()), "amount": 1}, headers=ph)
    ).status_code == 403


@pytest.mark.asyncio
async def test_normal_user_cannot_access_user_webhooks(client):
    """Normal user is forbidden from pro-only user-webhook endpoints."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    nh = normal["headers"]

    assert (await client.get("/webhooks", headers=nh)).status_code == 403
    assert (
        await client.post("/webhooks", json={"url": "https://x.com", "events": ["credit.request"]}, headers=nh)
    ).status_code == 403
    assert (await client.put(f"/webhooks/{uuid.uuid4()}", json={}, headers=nh)).status_code == 403
    assert (await client.delete(f"/webhooks/{uuid.uuid4()}", headers=nh)).status_code == 403


# ===========================================================================
# 4. Webhook-delivery scenarios
# ===========================================================================


def _make_mock_webhook_client(
    response_status: int = 200,
    side_effect=None,
    capture_calls: list | None = None,
) -> MagicMock:
    """Build a mock ``httpx.AsyncClient`` class for patching ``api.utils.webhooks.httpx``.

    The returned object is used as::

        with patch("api.utils.webhooks.httpx.AsyncClient", _make_mock_webhook_client(...)):
            ...

    Parameters
    ----------
    response_status:
        HTTP status code the mock POST should return (default 200).
    side_effect:
        Optional callable to use instead of returning a fixed response.
    capture_calls:
        If provided, each ``(url, content, headers)`` tuple is appended here.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = response_status
    mock_resp.is_success = 200 <= response_status < 300

    async def _default_post(url, *, content, headers, **kw):
        if capture_calls is not None:
            capture_calls.append((url, content, dict(headers)))
        return mock_resp

    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(side_effect=side_effect if side_effect else _default_post)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_class = MagicMock(return_value=mock_ctx)
    return mock_class, mock_instance


@pytest.mark.asyncio
async def test_system_webhook_fires_on_credit_request(client):
    """A system webhook subscribed to credit.request fires when a user requests credits."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    # Register system webhook
    await client.post(
        "/admin/webhooks",
        json={"url": "https://receiver.example.com/hook", "events": ["credit.request"], "active": True},
        headers=admin_headers,
    )

    calls: list = []
    mock_class, _ = _make_mock_webhook_client(capture_calls=calls)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": normal["id"], "amount": 5},
            headers=normal["headers"],
        )

    assert r.status_code == 202
    assert r.json()["webhooks_fired"] == 1
    assert len(calls) == 1
    assert calls[0][0] == "https://receiver.example.com/hook"


@pytest.mark.asyncio
async def test_user_webhook_fires_on_credit_request(client):
    """A user webhook (admin-owned) fires together with any system webhook on credit.request."""
    admin_headers = await _setup_admin(client)
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    # Admin creates a user-scoped webhook with credit.request (only admins can do this)
    await client.post(
        "/webhooks",
        json={"url": "https://pro-hook.example.com/events", "events": ["credit.request"], "active": True},
        headers=admin_headers,
    )

    calls: list = []
    mock_class, _ = _make_mock_webhook_client(capture_calls=calls)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": pro["id"], "amount": 3},
            headers=pro["headers"],
        )

    assert r.status_code == 202
    assert r.json()["webhooks_fired"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_webhook_hmac_signature(client):
    """When a webhook has a secret the X-Arcus-Signature header is set correctly."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    secret = "supersecret"
    await client.post(
        "/admin/webhooks",
        json={
            "url": "https://signed.example.com/hook",
            "secret": secret,
            "events": ["credit.request"],
            "active": True,
        },
        headers=admin_headers,
    )

    calls: list = []
    mock_class, _ = _make_mock_webhook_client(capture_calls=calls)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": normal["id"], "amount": 2},
            headers=normal["headers"],
        )

    assert r.status_code == 202
    assert len(calls) == 1
    _url, body, call_headers = calls[0]
    sig = call_headers.get("X-Arcus-Signature", "")
    assert sig.startswith("sha256=")
    _, hex_digest = sig.split("=", 1)

    expected_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert hex_digest == expected_sig


@pytest.mark.asyncio
async def test_inactive_webhook_not_fired(client):
    """Inactive webhooks are skipped during delivery."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    await client.post(
        "/admin/webhooks",
        json={"url": "https://inactive.example.com/hook", "events": ["credit.request"], "active": False},
        headers=admin_headers,
    )

    calls: list = []
    mock_class, _ = _make_mock_webhook_client(capture_calls=calls)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": normal["id"], "amount": 1},
            headers=normal["headers"],
        )

    assert r.status_code == 202
    assert r.json()["webhooks_fired"] == 0
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_wrong_event_webhook_not_fired(client):
    """A webhook subscribed to a different event is not fired for credit.request."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    await client.post(
        "/admin/webhooks",
        json={"url": "https://other.example.com/hook", "events": ["user.created"], "active": True},
        headers=admin_headers,
    )

    calls: list = []
    mock_class, _ = _make_mock_webhook_client(capture_calls=calls)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": normal["id"], "amount": 1},
            headers=normal["headers"],
        )

    assert r.status_code == 202
    assert r.json()["webhooks_fired"] == 0
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_webhook_delivery_failure_does_not_block_response(client):
    """A failing webhook delivery is logged but the credit request still returns 202."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    await client.post(
        "/admin/webhooks",
        json={"url": "https://broken.example.com/hook", "events": ["credit.request"], "active": True},
        headers=admin_headers,
    )

    async def _raise(url, *, content, headers, **kw):
        raise ConnectionError("simulated network failure")

    mock_class, _ = _make_mock_webhook_client(side_effect=_raise)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": normal["id"], "amount": 1},
            headers=normal["headers"],
        )

    assert r.status_code == 202
    assert r.json()["webhooks_fired"] == 0


@pytest.mark.asyncio
async def test_multiple_webhooks_all_fire(client):
    """When multiple active webhooks match the event, all are delivered."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    for i in range(3):
        await client.post(
            "/admin/webhooks",
            json={
                "url": f"https://hook{i}.example.com/events",
                "events": ["credit.request"],
                "active": True,
            },
            headers=admin_headers,
        )

    calls: list = []
    mock_class, _ = _make_mock_webhook_client(capture_calls=calls)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": normal["id"], "amount": 3},
            headers=normal["headers"],
        )

    assert r.status_code == 202
    assert r.json()["webhooks_fired"] == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_webhook_payload_structure(client):
    """Webhook delivery includes the correct envelope fields (event, fired_at, data)."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    await client.post(
        "/admin/webhooks",
        json={"url": "https://payload.example.com/hook", "events": ["credit.request"], "active": True},
        headers=admin_headers,
    )

    calls: list = []
    mock_class, _ = _make_mock_webhook_client(capture_calls=calls)
    with patch("api.utils.webhooks.httpx.AsyncClient", mock_class):
        r = await client.post(
            "/credits/request",
            json={"user_id": normal["id"], "amount": 10, "message": "need more credits"},
            headers=normal["headers"],
        )

    assert r.status_code == 202
    assert len(calls) == 1
    _url, body_bytes, _headers = calls[0]
    payload = json.loads(body_bytes)
    assert payload["event"] == "credit.request"
    assert "fired_at" in payload
    assert payload["data"]["user_id"] == normal["id"]
    assert payload["data"]["amount"] == 10
    assert payload["data"]["message"] == "need more credits"


# ===========================================================================
# 5. Role-access enforcement
# ===========================================================================


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(client):
    """All protected endpoints return 401 without credentials."""
    protected = [
        ("GET", "/auth/me"),
        ("GET", "/credits"),
        ("POST", "/credits/grant"),
        ("POST", "/credits/request"),
        ("POST", "/subdomains/purchase"),
        ("GET", "/subdomains"),
        ("POST", "/tokens"),
        ("GET", "/tokens"),
        ("GET", "/admin/users"),
        ("POST", "/admin/users"),
        ("GET", "/admin/webhooks"),
        ("POST", "/admin/webhooks"),
        ("GET", "/admin/blocklist"),
        ("POST", "/admin/blocklist"),
        ("GET", "/webhooks"),
        ("POST", "/webhooks"),
    ]
    for method, path in protected:
        r = await getattr(client, method.lower())(path)
        assert r.status_code == 401, f"{method} {path} should be 401, got {r.status_code}"


@pytest.mark.asyncio
async def test_normal_user_forbidden_from_admin_endpoints(client):
    """Normal user gets 403 from every admin-only endpoint."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    nh = normal["headers"]

    assert (await client.get("/admin/users", headers=nh)).status_code == 403
    assert (await client.post("/admin/users", json={"email": "x@x.com"}, headers=nh)).status_code == 403
    assert (
        await client.post(f"/admin/users/{uuid.uuid4()}/reset-password", headers=nh)
    ).status_code == 403
    assert (await client.get("/admin/webhooks", headers=nh)).status_code == 403
    assert (
        await client.post("/admin/webhooks", json={"url": "https://x.com", "events": []}, headers=nh)
    ).status_code == 403
    assert (await client.get("/admin/blocklist", headers=nh)).status_code == 403
    assert (await client.post("/admin/blocklist", json={"words": ["x"]}, headers=nh)).status_code == 403
    assert (
        await client.post("/credits/grant", json={"user_id": str(uuid.uuid4()), "amount": 1}, headers=nh)
    ).status_code == 403


# ===========================================================================
# 6. API-token authentication
# ===========================================================================


@pytest.mark.asyncio
async def test_admin_api_token_authentication(client):
    """Admin can authenticate with an arc_ API token."""
    admin_headers = await _setup_admin(client)

    r = await client.post("/tokens", json={"name": "admin-key"}, headers=admin_headers)
    assert r.status_code == 201
    raw_token = r.json()["token"]

    token_headers = {"Authorization": f"Bearer {raw_token}"}

    # Verify identity
    r = await client.get("/auth/me", headers=token_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    # Admin endpoint accessible with API token
    r = await client.get("/admin/users", headers=token_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_pro_api_token_authentication(client):
    """Pro user can authenticate with an arc_ API token."""
    admin_headers = await _setup_admin(client)
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    r = await client.post("/tokens", json={"name": "pro-key"}, headers=pro["headers"])
    assert r.status_code == 201
    raw_token = r.json()["token"]

    token_headers = {"Authorization": f"Bearer {raw_token}"}

    r = await client.get("/auth/me", headers=token_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "pro"

    # Pro can reach pro-only endpoint with API token
    r = await client.get("/webhooks", headers=token_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_normal_api_token_authentication(client):
    """Normal user can authenticate with an arc_ API token."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    r = await client.post("/tokens", json={"name": "normal-key"}, headers=normal["headers"])
    assert r.status_code == 201
    raw_token = r.json()["token"]

    token_headers = {"Authorization": f"Bearer {raw_token}"}

    r = await client.get("/auth/me", headers=token_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "normal"

    # Normal user is still forbidden from admin endpoints even via API token
    r = await client.get("/admin/users", headers=token_headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_revoked_api_token_rejected(client):
    """After revoking an API token it can no longer be used for authentication."""
    admin_headers = await _setup_admin(client)

    r = await client.post("/tokens", json={"name": "revokeme"}, headers=admin_headers)
    assert r.status_code == 201
    raw_token = r.json()["token"]
    token_id = r.json()["id"]

    # Revoke
    r = await client.delete(f"/tokens/{token_id}", headers=admin_headers)
    assert r.status_code == 204

    # Token no longer works
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {raw_token}"})
    assert r.status_code == 401


# ===========================================================================
# 7. Cookie-based authentication
# ===========================================================================


@pytest.mark.asyncio
async def test_cookie_auth_login_sets_cookie(client):
    """POST /auth/login sets an arcus_session HTTP-only cookie."""
    await client.post(
        "/auth/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    r = await client.post(
        "/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 200
    assert "arcus_session" in r.cookies


@pytest.mark.asyncio
async def test_cookie_auth_me_endpoint(client):
    """The arcus_session cookie is accepted for authenticated requests."""
    await client.post(
        "/auth/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    login_r = await client.post(
        "/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    cookie_value = login_r.cookies["arcus_session"]

    r = await client.get("/auth/me", cookies={"arcus_session": cookie_value})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_cookie_auth_logout_clears_cookie(client):
    """POST /auth/logout removes the arcus_session cookie."""
    await client.post(
        "/auth/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    await client.post(
        "/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    r = await client.post("/auth/logout")
    assert r.status_code == 204
    # Cookie should be cleared (set to empty / past expiry)
    assert "arcus_session" not in r.cookies or r.cookies.get("arcus_session") == ""


@pytest.mark.asyncio
async def test_cookie_auth_relogin_after_logout(client):
    """A browser-style client can log out and then establish a fresh session."""
    await client.post(
        "/auth/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )

    login_1 = await client.post(
        "/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login_1.status_code == 200
    assert client.cookies.get("arcus_session")

    me_1 = await client.get("/auth/me")
    assert me_1.status_code == 200

    logout = await client.post("/auth/logout")
    assert logout.status_code == 204
    assert client.cookies.get("arcus_session") is None

    me_2 = await client.get("/auth/me")
    assert me_2.status_code == 401

    login_2 = await client.post(
        "/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login_2.status_code == 200
    assert client.cookies.get("arcus_session")

    me_3 = await client.get("/auth/me")
    assert me_3.status_code == 200


@pytest.mark.asyncio
async def test_local_browser_pages_use_canonical_ui_host(client):
    """Local HTML routes must stay on api.localhost to keep cookie scope stable."""
    with patch.object(settings, "allow_private_origin_hosts", True), patch.object(settings, "base_domain", "localhost"):
        login = await client.get("/login?setup=1", headers={"host": "localhost:8000"}, follow_redirects=False)
        dashboard = await client.get("/dashboard", headers={"host": "localhost:8000"}, follow_redirects=False)

    assert login.status_code == 307
    assert login.headers["location"] == "http://api.localhost/login?setup=1"
    assert dashboard.status_code == 307
    assert dashboard.headers["location"] == "http://api.localhost/dashboard"


# ===========================================================================
# 8. Admin user management details
# ===========================================================================


@pytest.mark.asyncio
async def test_admin_list_users_after_creation(client):
    """GET /admin/users returns all users ordered by creation date."""
    admin_headers = await _setup_admin(client)

    emails = [f"user{i}@arcus.example.com" for i in range(3)]
    for email in emails:
        await _create_user_with_password(client, admin_headers, email, "normal")

    r = await client.get("/admin/users", headers=admin_headers)
    assert r.status_code == 200
    returned_emails = [u["email"] for u in r.json()]
    for email in emails:
        assert email in returned_emails
    # Admin itself is also in the list
    assert ADMIN_EMAIL in returned_emails


@pytest.mark.asyncio
async def test_admin_reset_password_forces_change(client):
    """POST /admin/users/{id}/reset-password sets must_change_password=True."""
    admin_headers = await _setup_admin(client)
    user = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")

    r = await client.post(f"/admin/users/{user['id']}/reset-password", headers=admin_headers)
    assert r.status_code == 204

    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == uuid.UUID(user["id"])))
        u = result.scalar_one()
        assert u.must_change_password is True


@pytest.mark.asyncio
async def test_admin_reset_password_unknown_user(client):
    """POST /admin/users/{id}/reset-password with unknown ID returns 404."""
    admin_headers = await _setup_admin(client)
    r = await client.post(f"/admin/users/{uuid.uuid4()}/reset-password", headers=admin_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_create_user_via_admin_endpoint(client):
    """POST /admin/users creates a user with must_change_password=True."""
    admin_headers = await _setup_admin(client)
    r = await client.post(
        "/admin/users",
        json={"email": "newuser@arcus.example.com", "role": "pro"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "newuser@arcus.example.com"
    assert data["role"] == "pro"
    assert data["must_change_password"] is True


@pytest.mark.asyncio
async def test_admin_only_one_admin_allowed(client):
    """POST /admin/users with role=admin returns 409 when an admin already exists."""
    admin_headers = await _setup_admin(client)
    r = await client.post(
        "/admin/users",
        json={"email": "admin2@arcus.example.com", "role": "admin"},
        headers=admin_headers,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_admin_duplicate_email_rejected(client):
    """POST /admin/users with an already-used e-mail returns 409."""
    admin_headers = await _setup_admin(client)
    await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    r = await client.post(
        "/admin/users",
        json={"email": NORMAL_EMAIL, "role": "normal"},
        headers=admin_headers,
    )
    assert r.status_code == 409


# ===========================================================================
# 9. Password change workflow
# ===========================================================================


@pytest.mark.asyncio
async def test_must_change_password_flag_cleared_after_change(client):
    """The must_change_password flag is cleared after the user changes their password."""
    admin_headers = await _setup_admin(client)

    # Create user via admin endpoint (must_change_password=True)
    resp = await client.post(
        "/admin/users",
        json={"email": NORMAL_EMAIL, "role": "normal"},
        headers=admin_headers,
    )
    assert resp.status_code == 201

    # Set a known password directly and simulate initial login
    user_id = resp.json()["id"]
    initial_password = "initialpwd1"
    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
        u = result.scalar_one()
        u.password_hash = hash_password(initial_password)
        # leave must_change_password=True
        await session.commit()

    login = await client.post("/auth/login", json={"email": NORMAL_EMAIL, "password": initial_password})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True

    token_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Change password
    new_password = "newpasswd99"
    r = await client.post(
        "/auth/change-password",
        json={"current_password": initial_password, "new_password": new_password},
        headers=token_headers,
    )
    assert r.status_code == 204

    # Re-login and check flag
    login2 = await client.post("/auth/login", json={"email": NORMAL_EMAIL, "password": new_password})
    assert login2.status_code == 200
    assert login2.json()["must_change_password"] is False


# ===========================================================================
# 10. Subdomain check (public endpoint)
# ===========================================================================


@pytest.mark.asyncio
async def test_subdomain_check_public_endpoint(client):
    """GET /subdomains/check is accessible without authentication."""
    r = await client.get("/subdomains/check?slug=mypublic")
    assert r.status_code == 200
    assert r.json()["available"] is True


@pytest.mark.asyncio
async def test_subdomain_check_becomes_unavailable_after_purchase(client):
    """After purchase, /subdomains/check reflects the new state."""
    admin_headers = await _setup_admin(client)
    normal = await _create_user_with_password(client, admin_headers, NORMAL_EMAIL, "normal")
    await client.post(
        "/credits/grant",
        json={"user_id": normal["id"], "amount": 2},
        headers=admin_headers,
    )

    before = await client.get("/subdomains/check?slug=checkbuy")
    assert before.json()["available"] is True

    await client.post(
        "/subdomains/purchase",
        json={"user_id": normal["id"], "slug": "checkbuy"},
        headers=normal["headers"],
    )

    after = await client.get("/subdomains/check?slug=checkbuy")
    assert after.json()["available"] is False


# ===========================================================================
# 11. Blocklist CSV import/export (admin)
# ===========================================================================


@pytest.mark.asyncio
async def test_blocklist_csv_round_trip(client):
    """Export blocklist to CSV and re-import with replace mode produces same words."""
    admin_headers = await _setup_admin(client)

    await client.post("/admin/blocklist", json={"words": ["word1", "word2", "word3"]}, headers=admin_headers)

    export_r = await client.get("/admin/blocklist/export", headers=admin_headers)
    assert export_r.status_code == 200
    csv_data = export_r.content

    # Replace with same CSV
    import_r = await client.post(
        "/admin/blocklist/import?mode=replace",
        content=csv_data,
        headers={**admin_headers, "content-type": "text/csv"},
    )
    assert import_r.status_code == 200
    assert import_r.json()["imported"] == 3

    list_r = await client.get("/admin/blocklist", headers=admin_headers)
    words = {e["word"] for e in list_r.json()}
    assert {"word1", "word2", "word3"} == words


# ===========================================================================
# 12. User webhook isolation (pro users cannot see each other's webhooks)
# ===========================================================================


@pytest.mark.asyncio
async def test_user_webhooks_are_isolated(client):
    """Pro users cannot see or modify another pro user's webhooks."""
    admin_headers = await _setup_admin(client)
    pro1 = await _create_user_with_password(client, admin_headers, "pro1@arcus.example.com", "pro")
    pro2 = await _create_user_with_password(client, admin_headers, "pro2@arcus.example.com", "pro")

    # pro1 creates a webhook
    r = await client.post(
        "/webhooks",
        json={"url": "https://pro1.example.com/hook", "events": ["user.created"], "active": True},
        headers=pro1["headers"],
    )
    assert r.status_code == 201
    wh_id = r.json()["id"]

    # pro2 cannot see it
    r = await client.get("/webhooks", headers=pro2["headers"])
    assert r.status_code == 200
    assert not any(w["id"] == wh_id for w in r.json())

    # pro2 cannot update it
    r = await client.put(f"/webhooks/{wh_id}", json={"active": False}, headers=pro2["headers"])
    assert r.status_code == 404

    # pro2 cannot delete it
    r = await client.delete(f"/webhooks/{wh_id}", headers=pro2["headers"])
    assert r.status_code == 404


# ===========================================================================
# 13. Admin webhook vs user webhook isolation
# ===========================================================================


@pytest.mark.asyncio
async def test_admin_cannot_modify_user_webhook_via_admin_endpoint(client):
    """Admin system-webhook endpoints cannot reach user-owned webhooks."""
    admin_headers = await _setup_admin(client)
    pro = await _create_user_with_password(client, admin_headers, PRO_EMAIL, "pro")

    # Pro creates user webhook
    r = await client.post(
        "/webhooks",
        json={"url": "https://user.example.com/hook", "events": ["user.created"], "active": True},
        headers=pro["headers"],
    )
    wh_id = r.json()["id"]

    # Admin system endpoint should not find user webhook
    r = await client.get(f"/admin/webhooks/{wh_id}", headers=admin_headers)
    assert r.status_code == 404

    r = await client.put(f"/admin/webhooks/{wh_id}", json={"active": False}, headers=admin_headers)
    assert r.status_code == 404

    r = await client.delete(f"/admin/webhooks/{wh_id}", headers=admin_headers)
    assert r.status_code == 404
