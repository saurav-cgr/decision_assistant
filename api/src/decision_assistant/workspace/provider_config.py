"""Persistence and application of the selected provider configuration (T050, US6/FR-016).

Provider names used to come only from `.env`, so a switch could not survive a restart. The single
row in `app_settings` (migration `0017`) now holds them, and `apply_stored_provider_config` overlays
that row onto the process-wide `Settings` at startup — which keeps one effective configuration for
ingestion, retrieval, answering and readiness instead of a second source that could disagree.

Scope, stated plainly: the row is global, not per workspace. The HTTP route *is* per workspace
(authorization and the rebuild it triggers are workspace-scoped), but a local single-tenant install
has one provider configuration. Making the choice per workspace would mean threading workspace
configuration through every provider call in ingestion/retrieval/answering — a much larger change,
recorded as debt rather than smuggled in here.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.config import Settings
from decision_assistant.models import Base

#: The single row's primary key. `ck_app_settings_single_row` refuses any other value.
APP_SETTINGS_ID = 1


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_app_settings_single_row"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=APP_SETTINGS_ID)
    generation_provider: Mapped[str] = mapped_column(String(32))
    embedding_provider: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


async def load_stored_provider_config(session: AsyncSession) -> AppSettings | None:
    """The stored provider configuration, or None before anything has been switched."""
    return await session.get(AppSettings, APP_SETTINGS_ID)


def apply_stored_provider_config(settings: Settings, stored: AppSettings) -> Settings:
    """Overlay the stored provider names onto `settings` in place and return it.

    In place on purpose: `main.py` sets `app.state.settings = resolved_settings` and every consumer
    (provider factory, readiness check, corpus-profile resolution) reads that one object, so mutating
    it before those run is what makes the stored choice take effect without a second configuration
    source.
    """
    settings.generation_provider = stored.generation_provider
    settings.embedding_provider = stored.embedding_provider
    return settings


async def store_provider_config(
    session: AsyncSession,
    *,
    generation_provider: str,
    embedding_provider: str,
) -> AppSettings:
    """Upsert the single row and return it (flushed, not committed — the caller owns the commit)."""
    stored = await session.get(AppSettings, APP_SETTINGS_ID)
    if stored is None:
        stored = AppSettings(
            id=APP_SETTINGS_ID,
            generation_provider=generation_provider,
            embedding_provider=embedding_provider,
        )
        session.add(stored)
    else:
        stored.generation_provider = generation_provider
        stored.embedding_provider = embedding_provider
    await session.flush()
    return stored


async def active_rebuild_workspace_ids(session: AsyncSession) -> list[object]:
    """Workspace ids with a `pending`/`running` rebuild anywhere in the process (DB57).

    The guard is deliberately not per workspace. The stored provider configuration is one global
    row, so a switch confirmed while *another* workspace rebuilds would let that rebuild keep the
    provider bundle it captured at dispatch time and finish writing a corpus under the old
    embedding profile while `app_settings` already reports the new one.
    """
    from decision_assistant.workspace.rebuild_models import CorpusRebuild

    rows = await session.scalars(
        select(CorpusRebuild.workspace_id)
        .where(CorpusRebuild.status.in_(("pending", "running")))
        .distinct()
    )
    return list(rows)


#: Advisory-lock key for a provider switch (DB68). Deliberately a constant rather than a
#: workspace-derived key: the guard it protects is process-wide, because the stored configuration is
#: one global row, so switches on different workspaces have to serialise with each other too.
PROVIDER_SWITCH_LOCK_KEY = int.from_bytes(b"provider", "big")


async def acquire_provider_switch_lock(session: AsyncSession) -> None:
    """Serialise provider switches for the rest of this transaction (DB68).

    `active_rebuild_workspace_ids` is a plain read and the unique partial index on `corpus_rebuilds`
    is per workspace, so two switches confirmed at the same time on *different* workspaces can both
    see no active rebuild, both persist `app_settings` and both dispatch a rebuild. The last write
    then wins — DB57's divergence reached through a race. Taking this lock before that read makes the
    second switch wait for the first transaction to commit, after which it sees the rebuild the
    first one just dispatched. Same `pg_advisory_xact_lock` pattern as
    `workspace/embedding_profile.py`; the lock is released when the transaction ends.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(PROVIDER_SWITCH_LOCK_KEY))
    )
