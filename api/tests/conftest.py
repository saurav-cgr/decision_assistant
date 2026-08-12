import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import decision_assistant.config as config_module
from decision_assistant.config import get_settings

API_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "decision_assistant_test"

# Repoint every settings consumer (tests, alembic, inline-built engines) at a
# dedicated test database before any test module imports get_settings(). Because
# consumers do `from decision_assistant.config import get_settings`, the shared
# function object is the single source of truth: set DATABASE_URL and clear its
# cache so the next call resolves the test URL.
_real_settings = get_settings()
TEST_DATABASE_URL = make_url(_real_settings.database_url).set(
    database=TEST_DB_NAME
).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
config_module.get_settings.cache_clear()

_APP_TABLES = (
    "workspaces",
    "documents",
    "document_versions",
    "passages",
    "decisions",
    "decision_evidence",
    "decision_relations",
    "decision_revisions",
    "ingestion_jobs",
    "retrieval_traces",
    "evaluation_questions",
    "evaluation_runs",
    "evaluation_results",
)


async def _ensure_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    conn = await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


async def _truncate_all() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE")
        )
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _isolated_test_database() -> None:
    asyncio.run(_ensure_test_database())
    alembic_cfg = Config(str(API_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")
    asyncio.run(_truncate_all())


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()
