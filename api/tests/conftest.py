"""Shared pytest fixtures for the Arcus API test suite.

Uses an in-memory SQLite database (via aiosqlite) so tests run without a real
PostgreSQL instance.  The application's async engine is replaced before the
app is imported so all ORM calls hit the test database.

Limitation: SQLite does not support PostgreSQL-specific types (UUID, TIMESTAMPTZ)
or transaction isolation semantics.  For full integration coverage, run the stack
with ``docker compose up`` and point DATABASE_URL at a real PostgreSQL instance.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# ---------------------------------------------------------------------------
# Override the database URL *before* any application module is loaded so that
# the engine that ``database.py`` creates points at SQLite.
# ---------------------------------------------------------------------------
import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CLOUDFLARE_API_TOKEN", "")
os.environ.setdefault("CLOUDFLARE_ZONE_ID", "")

from api.database import Base, get_db  # noqa: E402 – must come after env override
from api.main import app               # noqa: E402

# ---------------------------------------------------------------------------
# Build a fresh in-process engine for every test session
# ---------------------------------------------------------------------------
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
