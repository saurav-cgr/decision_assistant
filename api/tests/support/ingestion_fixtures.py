"""Shared helpers for integration tests that run the real ingestion dispatch path.

`LocalIngestionDispatcher` is the code that actually parses and indexes a document, so tests that
want to prove what happens to a real job (a timeout, a crash-left row, a provider outage) need the
real dispatcher, not the `RecordingDispatcher` stub the upload tests use. Three pieces make that
work, and they are here rather than duplicated per file:

* `FakeProviderBundleFactory` — deterministic providers, so no live model call.
* `loop_local_dispatch_session_factory` — the dispatch path binds `session_factory` from
  `decision_assistant.db` at import time, and that engine is a process-wide singleton created against
  whichever event loop first opened a connection. Each async test gets a fresh loop, so the second
  test in a session would otherwise fail with "Future ... attached to a different loop".
* `cleanup_workspace` — the test database is truncated once per pytest session, not per test, so a
  test that really ingests must delete its workspace (`ON DELETE CASCADE` clears the derived rows)
  or it pollutes another file's unscoped counts.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from decision_assistant.config import get_settings
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import FakeEmbeddingProvider, FakeGenerationProvider
from decision_assistant.workspace.models import Workspace


class FakeProviderBundleFactory:
    """Replaces `CachedProviderBundleFactory` so the real dispatch path runs offline."""

    def __init__(self) -> None:
        self.embedding = FakeEmbeddingProvider(dimension=768)
        self.generation = FakeGenerationProvider([{"decisions": []}] * 10)

    def __call__(self) -> ProviderBundle:
        return ProviderBundle(embedding=self.embedding, generation=self.generation)

    async def aclose(self) -> None:
        return None


@asynccontextmanager
async def loop_local_dispatch_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import decision_assistant.documents.router as router_module

    monkeypatch.setattr(router_module, "session_factory", factory)
    try:
        yield
    finally:
        await engine.dispose()


@asynccontextmanager
async def cleanup_workspace(
    db_session: AsyncSession, workspace_id: UUID
) -> AsyncIterator[None]:
    try:
        yield
    finally:
        workspace = await db_session.get(Workspace, workspace_id)
        if workspace is not None:
            await db_session.delete(workspace)
            await db_session.commit()
