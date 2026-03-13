"""Pytest fixtures for the Arcus Router test suite.

Uses an in-memory SQLite database and a mocked httpx client so the router can
be tested without a real PostgreSQL instance or upstream origin server.
"""

import os
import uuid

import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("BASE_DOMAIN", "thesoftware.dev")

from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import router.main as router_module
from router.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

_DDL = [
    """CREATE TABLE IF NOT EXISTS users (
        id   TEXT PRIMARY KEY,
        email TEXT,
        role TEXT NOT NULL DEFAULT 'normal'
    )""",
    """CREATE TABLE IF NOT EXISTS subdomains (
        id          TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        slug        TEXT UNIQUE NOT NULL,
        origin_host TEXT,
        origin_port INTEGER,
        active      INTEGER NOT NULL DEFAULT 1
    )""",
]


@pytest_asyncio.fixture(autouse=True)
async def setup_router_db(monkeypatch):
    """Create tables, override module-level SessionLocal, drop tables on teardown."""
    monkeypatch.setattr(router_module, "SessionLocal", TestSessionLocal)

    async with test_engine.begin() as conn:
        for stmt in _DDL:
            await conn.execute(text(stmt))
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS subdomains"))
        await conn.execute(text("DROP TABLE IF EXISTS users"))


@pytest_asyncio.fixture
async def mock_http_client(monkeypatch):
    """Replace the router's httpx client with a mock that returns 200."""
    mock = AsyncMock()
    mock.request = AsyncMock(
        return_value=Response(200, content=b"origin ok", headers={"content-type": "text/plain"})
    )
    monkeypatch.setattr(router_module, "_http_client", mock)
    return mock


@pytest_asyncio.fixture
async def client(mock_http_client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def insert_subdomain(role: str = "normal", slug: str = "testslug",
                            origin_host: str = "203.0.113.1", origin_port: int = 8080) -> str:
    user_id = str(uuid.uuid4())
    async with TestSessionLocal() as session:
        await session.execute(
            text("INSERT INTO users (id, email, role) VALUES (:id, :email, :role)"),
            {"id": user_id, "email": f"{role}-{slug}@test.com", "role": role},
        )
        await session.execute(
            text(
                "INSERT INTO subdomains (id, user_id, slug, origin_host, origin_port) "
                "VALUES (:id, :uid, :slug, :host, :port)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "slug": slug,
             "host": origin_host, "port": origin_port},
        )
        await session.commit()
    return user_id
