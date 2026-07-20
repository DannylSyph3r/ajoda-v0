"""
Pytest fixtures for the Ajoda backend test suite.

The models are Postgres-specific (UUID / ARRAY / JSONB) and the future-period
upsert uses Postgres `ON CONFLICT`, so SQLite cannot stand in — the suite runs
against a real, throwaway Postgres database supplied via TEST_DATABASE_URL, e.g.

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/ajoda_test pytest

If TEST_DATABASE_URL is unset, DB-backed tests are skipped (not failed), so the
suite still collects and green-lights on a machine without a test database.
"""
import importlib
import os
import pkgutil

# Satisfy the app's required Settings() fields at import time so modules that call
# get_settings() at load (e.g. payment_service) can be imported by the test suite.
# setdefault() means a real environment always wins; these dummies are never used
# for an actual connection — DB tests use TEST_DATABASE_URL via the engine fixture.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/ajoda_dummy")
os.environ.setdefault("META_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("META_VERIFY_TOKEN", "test")
os.environ.setdefault("META_APP_SECRET", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("INTERNAL_CRON_SECRET", "test")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401,E402  — populates Base.metadata with every table
from app.models.base import Base  # noqa: E402

# Import every model module so all tables register on Base.metadata (create_all
# needs the full FK graph, not just the tables a given test touches).
for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _to_asyncpg_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@pytest_asyncio.fixture(scope="session")
async def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set — skipping DB-backed tests")
    eng = create_async_engine(_to_asyncpg_url(TEST_DATABASE_URL))
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
def session_factory(engine):
    """A sessionmaker bound to the test engine, for tests that need >1 session."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def db(session_factory):
    """A single AsyncSession for a test. Tests commit freely."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(engine):
    """
    Wipe every table after each test. Tests commit (the code under test commits),
    so transactional rollback isolation is not available — we truncate instead,
    in reverse FK-dependency order.
    """
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
