"""Tests for admin user-management updates (role, activation, delete)."""

import pytest

from api.tests.conftest import NORMAL_EMAIL, NORMAL_PASSWORD


@pytest.mark.asyncio
async def test_admin_can_update_user_role(client, admin_headers, normal_user):
    resp = await client.patch(
        f"/admin/users/{normal_user['id']}",
        json={"role": "pro"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "pro"


@pytest.mark.asyncio
async def test_deactivated_user_cannot_authenticate(client, admin_headers, normal_user):
    resp = await client.patch(
        f"/admin/users/{normal_user['id']}",
        json={"active": False},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    me = await client.get("/auth/me", headers=normal_user["headers"])
    assert me.status_code == 403

    login = await client.post(
        "/auth/login",
        json={"email": NORMAL_EMAIL, "password": NORMAL_PASSWORD},
    )
    assert login.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_user(client, admin_headers, normal_user):
    resp = await client.delete(f"/admin/users/{normal_user['id']}", headers=admin_headers)
    assert resp.status_code == 204

    get_deleted = await client.get(f"/admin/users/{normal_user['id']}", headers=admin_headers)
    assert get_deleted.status_code == 404

    login = await client.post(
        "/auth/login",
        json={"email": NORMAL_EMAIL, "password": NORMAL_PASSWORD},
    )
    assert login.status_code == 401


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_self(client, admin_headers):
    me = await client.get("/auth/me", headers=admin_headers)
    assert me.status_code == 200
    resp = await client.patch(
        f"/admin/users/{me.json()['id']}",
        json={"active": False},
        headers=admin_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(client, admin_headers):
    me = await client.get("/auth/me", headers=admin_headers)
    assert me.status_code == 200
    resp = await client.delete(f"/admin/users/{me.json()['id']}", headers=admin_headers)
    assert resp.status_code == 400
