"""Shared pytest fixtures for the Arcus API test suite.

Uses an in-memory SQLite database (via aiosqlite) so tests run without a real
PostgreSQL instance.  The application's async engine is replaced before the
app is imported so all ORM calls hit the test database.
"""

import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CLOUDFLARE_API_TOKEN", "")
os.environ.setdefault("CLOUDFLARE_ZONE_ID", "")

from api.database import Base, get_db  # noqa: E402
from api.main import app  # noqa: E402

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
ADMIN_PASSWORD = "TestAdmin1!"


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
