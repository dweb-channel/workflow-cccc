"""Root conftest for API and repository tests.

Provides:
- In-memory SQLite database (replaces production engine)
- FastAPI TestClient with mocked Temporal
- Reusable fixtures for batch jobs, workspaces, etc.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

import app.database as db_module
from app.database import Base

# Import all ORM models so they register with Base.metadata
import app.models.db  # noqa: F401


# ---------------------------------------------------------------------------
# In-memory async SQLite engine (StaticPool shares one connection)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an in-memory SQLite engine shared across all tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test database session with automatic rollback."""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()

    # Clean all tables between tests
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


# ---------------------------------------------------------------------------
# Temporal mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_temporal_client():
    """Mock Temporal client for route tests."""
    client = AsyncMock()
    client.start_workflow = AsyncMock(return_value=MagicMock(id="test-wf-id"))
    handle = MagicMock()
    handle.cancel = AsyncMock()
    client.get_workflow_handle = MagicMock(return_value=handle)
    return client


# ---------------------------------------------------------------------------
# FastAPI test client — patches DB engine + Temporal at module level
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(
    test_engine: AsyncEngine,
    mock_temporal_client,
) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing FastAPI routes.

    Replaces the production DB engine/session_factory in app.database
    with the test in-memory engine, so all get_session_ctx() calls
    throughout the codebase use the test DB.
    """
    # Replace the real engine and session_factory with test versions
    original_engine = db_module.engine
    original_factory = db_module.async_session_factory

    test_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    db_module.engine = test_engine
    db_module.async_session_factory = test_factory

    try:
        with patch("app.temporal_adapter.get_client", AsyncMock(return_value=mock_temporal_client)):
            with patch("app.routes.batch.get_client", AsyncMock(return_value=mock_temporal_client)):
                from app.main import app

                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    yield ac
    finally:
        # Restore original engine
        db_module.engine = original_engine
        db_module.async_session_factory = original_factory

    # Clean tables after each test
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
