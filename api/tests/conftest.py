"""Shared pytest fixtures for the Arcus API test suite.

Uses an in-memory SQLite database (via aiosqlite) so tests run without a real
PostgreSQL instance.  The application's async engine is replaced before the
app is imported so all ORM calls hit the test database.
"""

import os
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CLOUDFLARE_API_TOKEN", "")
os.environ.setdefault("CLOUDFLARE_ZONE_ID", "")

from api.database import Base, get_db  # noqa: E402
from api.main import app  # noqa: E402
from api.models import User  # noqa: E402
from api.utils.auth import hash_password  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create all tables before each test, drop them afterwards."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Return an ``AsyncClient`` wired to the FastAPI test app."""

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "admin@test.arcus"
ADMIN_PASSWORD = "testadmin12"

PRO_EMAIL = "pro@test.arcus"
PRO_PASSWORD = "testpro1234"

NORMAL_EMAIL = "normal@test.arcus"
NORMAL_PASSWORD = "testnorm12"


@pytest_asyncio.fixture
async def admin_token(client):
    """Create the admin user via /auth/setup and return a JWT access token."""
    resp = await client.post(
        "/auth/setup",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 201, resp.text

    login_resp = await client.post(
        "/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 200, login_resp.text
    return login_resp.json()["access_token"]


@pytest_asyncio.fixture
async def admin_headers(admin_token):
    """Return HTTP headers with admin Bearer JWT."""
    return {"Authorization": f"Bearer {admin_token}"}


async def _create_user_with_known_password(client, admin_headers: dict, email: str, role: str, password: str) -> dict:
    """Create a user via admin and inject a known password directly into the DB.

    Returns a dict with ``id``, ``headers``.
    """
    resp = await client.post("/admin/users", json={"email": email, "role": role}, headers=admin_headers)
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
    return {"id": user_id, "headers": {"Authorization": f"Bearer {token}"}}


@pytest_asyncio.fixture
async def pro_user(client, admin_headers):
    """Create a pro user and return its id and auth headers."""
    return await _create_user_with_known_password(client, admin_headers, PRO_EMAIL, "pro", PRO_PASSWORD)


@pytest_asyncio.fixture
async def normal_user(client, admin_headers):
    """Create a normal user and return its id and auth headers."""
    return await _create_user_with_known_password(client, admin_headers, NORMAL_EMAIL, "normal", NORMAL_PASSWORD)
