"""DB72(a)/V173 and DB73: the manual rebuild retry must be ordered against a provider switch.

`POST /workspaces/{id}/corpus-rebuild/retry` and `POST /workspaces/{id}/provider` both write a
`pending` `CorpusRebuild`, so both take the process-wide advisory lock. Taking it is not enough on
its own: everything the retry resolves *before* the lock describes a world that may have changed
while it waited, and a confirmed switch does two things there — it replaces the cached provider
bundle and mutates `settings` in place. These tests pin the two consequences:

* the rebuild is dispatched with the factory that exists *after* the lock, not the request-time
  dependency (V173: a retry queued behind a switch used to run the new configuration's rebuild with
  the superseded bundle);
* the "latest rebuild is `failed`" precondition is re-read under the lock, so a retry that loses the
  race answers the documented 409 instead of hitting the single-active-rebuild unique index (DB73).

They live in their own module rather than in `test_workspaces_api.py` because that file is already
close to AGENTS.md's 500-line cap and this fixture needs the app object, which its fixture does not
expose. No provider client is constructed — the factory is a stub, and the only dispatched work is a
recorder.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.auth.models import User
from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.main import create_app
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.provider_config import (
    acquire_provider_switch_lock as real_switch_lock,
)
from decision_assistant.workspace.rebuild_models import CorpusRebuild


class _BundleFactory:
    """Stands in for `CachedProviderBundleFactory`; its bundles are told apart by identity."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __call__(self) -> object:
        return self

    async def aclose(self) -> None:
        return None


@pytest_asyncio.fixture
async def retry_api(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI, Workspace, list[dict]]]:
    import decision_assistant.workspace.router as router_module

    dispatches: list[dict] = []

    async def _record_dispatch(*_args: object, **kwargs: object) -> None:
        dispatches.append(kwargs)

    monkeypatch.setattr(router_module, "dispatch_pending_rebuild", _record_dispatch)

    owner = User(
        username=f"retry-owner-{uuid4()}",
        password_hash="unused",
        recovery_code_hash="unused",
    )
    db_session.add(owner)
    await db_session.flush()
    workspace = Workspace(name=f"Retry {uuid4()}", owner_user_id=owner.id)
    db_session.add(workspace)
    await db_session.flush()

    settings = Settings(
        upload_directory=tmp_path,
        auth_jwt_secret=SecretStr("test-signing-secret-for-rebuild-retry"),
        gemini_api_key=SecretStr("fake-gemini-key-for-rebuild-retry"),
        generation_provider="gemini",
        embedding_provider="gemini",
    )
    app = create_app(settings)
    app.state.provider_bundle_factory = _BundleFactory("initial")

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: owner
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, app, workspace, dispatches


async def _seed_failed_rebuild(session: AsyncSession, workspace_id: UUID) -> None:
    """A `failed` rebuild, five minutes older than anything the request itself writes.

    `created_at`'s `server_default=func.now()` is the transaction timestamp, so without an explicit
    earlier value this row and a row inserted by the request would tie in `_latest_rebuild`'s
    ordering.
    """
    session.add(
        CorpusRebuild(
            workspace_id=workspace_id,
            status="failed",
            reason="corpus_reset_required",
            documents_total=1,
            documents_completed=0,
            error={"code": "ingestion_failed"},
            created_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    await session.flush()


def _retry_url(workspace_id: UUID) -> str:
    return f"/api/v1/workspaces/{workspace_id}/corpus-rebuild/retry"


async def test_retry_dispatches_with_the_factory_that_exists_after_the_lock(
    retry_api: tuple[httpx.AsyncClient, FastAPI, Workspace, list[dict]],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB72(a)/V173: a switch that wins the lock must not be out-run by the retry behind it.

    `Depends` resolves the provider bundle factory before the route body runs, so dispatching with
    that value means a retry queued behind a confirmed switch re-ingests the corpus with the bundle
    the switch has just superseded and closed, while `app_settings` already reports the new
    provider. Replacing the cached factory at the moment the lock is taken is that interleaving.
    """
    import decision_assistant.workspace.router as router_module

    client, app, workspace, dispatches = retry_api
    await _seed_failed_rebuild(db_session, workspace.id)
    superseded = app.state.provider_bundle_factory
    replacement = _BundleFactory("after-switch")

    async def _switch_wins_then_lock(session: AsyncSession) -> None:
        app.state.provider_bundle_factory = replacement
        await real_switch_lock(session)

    monkeypatch.setattr(router_module, "acquire_provider_switch_lock", _switch_wins_then_lock)

    response = await client.post(_retry_url(workspace.id))

    assert response.status_code == 202
    assert len(dispatches) == 1
    assert dispatches[0]["providers"] is not superseded
    assert dispatches[0]["providers"] is replacement, (
        "the retry dispatched the provider bundle resolved before the lock, so a confirmed switch "
        "that won the lock leaves the rebuild running under the superseded provider (DB72a)"
    )


async def test_retry_rechecks_the_precondition_under_the_lock(
    retry_api: tuple[httpx.AsyncClient, FastAPI, Workspace, list[dict]],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB73: a retry that loses the race answers 409, not 500.

    The status check runs before the lock, so the loser's own read still saw the old `failed` row.
    The interleaving is modelled by inserting the winner's committed `pending` row inside the lock:
    with the re-check the request answers `corpus_rebuild_not_retryable` and dispatches nothing;
    without it its own insert collides with the single-active-rebuild unique index, and that
    `IntegrityError` has no handler (500 in production, an escaping exception under ASGITransport).
    """
    import decision_assistant.workspace.router as router_module

    client, _app, workspace, dispatches = retry_api
    await _seed_failed_rebuild(db_session, workspace.id)

    async def _winner_takes_the_lock(session: AsyncSession) -> None:
        session.add(
            CorpusRebuild(
                workspace_id=workspace.id,
                status="pending",
                reason="manual_retry",
                documents_total=0,
                documents_completed=0,
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()
        await real_switch_lock(session)

    monkeypatch.setattr(router_module, "acquire_provider_switch_lock", _winner_takes_the_lock)

    response = await client.post(_retry_url(workspace.id))

    assert response.status_code == 409
    assert response.json()["code"] == "corpus_rebuild_not_retryable"
    assert dispatches == []
