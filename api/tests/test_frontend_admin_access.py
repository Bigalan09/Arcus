"""Frontend access checks for admin pages."""

import uuid

import pytest


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
