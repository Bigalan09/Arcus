"""Frontend access checks for admin pages."""

import uuid
from unittest.mock import patch

import pytest

from api.config import settings


@pytest.mark.asyncio
async def test_admin_page_requires_auth(client):
    resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_admin_page_rejects_non_admin(client, normal_user):
    resp = await client.get("/admin", headers=normal_user["headers"], follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_admin_page_allows_admin(client, admin_headers):
    resp = await client.get("/admin", headers=admin_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_user_page_requires_auth(client):
    resp = await client.get(f"/admin/users/{uuid.uuid4()}/manage", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_admin_user_page_rejects_non_admin(client, normal_user):
    resp = await client.get(
        f"/admin/users/{normal_user['id']}/manage",
        headers=normal_user["headers"],
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_admin_user_page_allows_admin(client, admin_headers):
    created = await client.post("/admin/users", json={"email": "managed@example.com", "role": "normal"}, headers=admin_headers)
    assert created.status_code == 201
    user_id = created.json()["id"]
    resp = await client.get(f"/admin/users/{user_id}/manage")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_local_login_page_redirects_to_canonical_ui_host(client):
    with patch.object(settings, "allow_private_origin_hosts", True), patch.object(settings, "base_domain", "localhost"):
        resp = await client.get("/login?setup=1", headers={"host": "localhost:8000"}, follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"] == "http://api.localhost/login?setup=1"


@pytest.mark.asyncio
async def test_local_dashboard_redirects_to_canonical_ui_host(client):
    with patch.object(settings, "allow_private_origin_hosts", True), patch.object(settings, "base_domain", "localhost"):
        resp = await client.get("/dashboard", headers={"host": "localhost:8000"}, follow_redirects=False)

    assert resp.status_code == 307
    assert resp.headers["location"] == "http://api.localhost/dashboard"


@pytest.mark.asyncio
async def test_admin_dashboard_shows_content_filter_bypass_toggle(client, admin_headers):
    resp = await client.get("/dashboard", headers=admin_headers)

    assert resp.status_code == 200
    assert "Ignore content filters" in resp.text


@pytest.mark.asyncio
async def test_normal_dashboard_hides_content_filter_bypass_toggle(client, normal_user):
    resp = await client.get("/dashboard", headers=normal_user["headers"])

    assert resp.status_code == 200
    assert "Ignore content filters" not in resp.text
