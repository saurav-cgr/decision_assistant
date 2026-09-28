"""T027: the upgrade rebuild's HTTP lifecycle, end to end (quickstart.md Section 4).

This is the layer the dispatcher-level tests (`test_corpus_rebuild_progress.py`,
`test_corpus_rebuild_run.py`) deliberately do not cover, and the checker asked for
it by name in iteration 62's handoff:

- The rebuild is triggered by the real `lifespan` startup scan, not by calling
  `dispatch_corpus_rebuild` directly: a workspace whose active corpus no longer
  matches the configured chunking preset must be detected and re-dispatched on
  its own.
- `GET /api/v1/workspaces/{id}/corpus-rebuild` must be readable *while* the
  rebuild runs, and must report `running` before it reports `completed` (DB41).
- Every read an operator can make mid-rebuild (`GET .../decisions`,
  `GET .../conversations`, `GET .../conversations/{id}`) must keep returning the
  pre-upgrade data at every polled point — the guarantee the whole design trades
  per-document progress away for (V108).

Exactly two things may differ once it finishes, and both are normalized out of
the comparison instead of being asserted equal: the passage/document-version ids
the re-link rewrites (DB40, asserted separately as "the decision still resolves")
and the conversation `stale` flag that follows them. Everything else in those
responses — statements, statuses, stored quotes, titles, turn numbers, questions,
answers, timestamps — is compared byte for byte on every poll.

Two app instances, two chunking presets, committed rows and their own engine:
the rebuild runs in background tasks with their own sessions, so the shared
`db_session` fixture (never committed) cannot drive it. Rows this test commits
are deleted in its `finally` (M-037).
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import decision_assistant.main as main_module
from decision_assistant.answering.conversation_models import (
    Conversation,
    ConversationMessage,
)
from decision_assistant.answering.schemas import (
    AnswerState,
    ConfidenceCategory,
    QuestionResponse,
)
from decision_assistant.auth.dependencies import get_current_user
from decision_assistant.auth.models import User
from decision_assistant.config import Settings
from decision_assistant.db import create_engine, get_session
from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.models import Document, Passage
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.main import create_app
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.workspace.context import WorkspaceContext, get_workspace_context
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.rebuild_models import CorpusRebuild

_METADATA_RESPONSE = {
    "title": "Architecture Sync",
    "document_date": "2026-07-15",
    "participants": ["Maya", "Ravi"],
    "source_type": "meeting",
    "project": "Atlas",
}

_SOURCE_TEXT = """---
title: Architecture Sync
date: 2026-07-15
participants: [Maya, Ravi]
source_type: meeting
project: Atlas
---

# Authentication

Authentication was postponed until the import flow is stable.
"""

_QUOTED_SENTENCE = "Authentication was postponed until the import flow is stable."

# Ids the rebuild legitimately rewrites (DB40's re-link) and the flag derived
# from the workspace revision that follows them. Everything else must not move.
_REWRITTEN_KEYS = frozenset({"passage_id", "document_version_id", "stale"})

_POLL_INTERVAL_SECONDS = 0.05
_POLL_TIMEOUT_SECONDS = 90.0


class _GatedEmbeddingProvider(FakeEmbeddingProvider):
    """Signals the first embedding call, then waits for release."""

    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(dimension=768)
        self._started = started
        self._release = release
        self._gated = False

    async def embed(self, texts, *, purpose):  # noqa: ANN001, ANN201 - provider protocol
        if not self._gated:
            self._gated = True
            self._started.set()
            await self._release.wait()
        return await super().embed(texts, purpose=purpose)


class _FakeBundleFactory:
    """Stand-in for the Gemini factory: the rebuild re-ingests through it.

    The fake providers are fast enough to finish inside a single poll interval,
    which would make `running` unobservable over HTTP and the transition
    assertion racy. The gate holds the rebuild open at its most representative
    moment (re-ingesting a document) until the test has polled `running` with
    stable reads — the same technique `test_corpus_rebuild_progress.py` uses at
    dispatcher level.
    """

    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        self._started = started
        self._release = release

    def __call__(self) -> ProviderBundle:
        return ProviderBundle(
            embedding=_GatedEmbeddingProvider(self._started, self._release),
            generation=FakeGenerationProvider([_METADATA_RESPONSE]),
        )

    async def aclose(self) -> None:
        return None


def _normalized(payload: object) -> object:
    """Drop the fields a completed rebuild is allowed to rewrite."""
    if isinstance(payload, dict):
        return {
            key: _normalized(value)
            for key, value in payload.items()
            if key not in _REWRITTEN_KEYS
        }
    if isinstance(payload, list):
        return [_normalized(item) for item in payload]
    return payload


async def _seed(factory: async_sessionmaker[AsyncSession], tmp_path: Path) -> dict:
    workspace_id = uuid4()
    document_id = uuid4()
    conversation_id = uuid4()
    upload_directory = tmp_path / "uploads"
    source_path = tmp_path / "source" / "meeting.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(_SOURCE_TEXT, encoding="utf-8")

    async with factory() as session:
        # Every business route is owner-scoped, so the workspace needs an owner
        # before any read can find it.
        owner = User(
            username=f"upgrade-owner-{uuid4()}",
            password_hash="unused",
            recovery_code_hash="unused",
        )
        session.add(owner)
        await session.flush()
        session.add(
            Workspace(
                id=workspace_id,
                name=f"Upgrade flow {workspace_id}",
                owner_user_id=owner.id,
            )
        )
        await session.flush()
        session.add(
            Document(
                id=document_id,
                workspace_id=workspace_id,
                display_name="meeting.md",
                media_type="text/markdown",
            )
        )
        await session.flush()
        service = IngestionService(
            session=session,
            embedding_provider=FakeEmbeddingProvider(dimension=768),
            decision_extractor=DecisionExtractor(FakeGenerationProvider()),
            metadata_extractor=MetadataExtractor(
                FakeGenerationProvider([_METADATA_RESPONSE])
            ),
            upload_directory=upload_directory,
        )
        result = await service.ingest(
            document_id,
            source_path,
            request_id=str(uuid4()),
            job_id=None,
            extract_decisions=False,
        )
        await session.flush()

        passage = next(
            p
            for p in await session.scalars(
                select(Passage).where(Passage.document_version_id == result.version_id)
            )
            if _QUOTED_SENTENCE in p.content
        )
        start_offset = passage.content.find(_QUOTED_SENTENCE)
        decision = Decision(
            workspace_id=workspace_id,
            document_version_id=result.version_id,
            statement="Authentication was postponed.",
            status="active",
            provenance="extracted",
            review_state="supported",
        )
        session.add(decision)
        await session.flush()
        session.add(
            DecisionEvidence(
                decision_id=decision.id,
                passage_id=passage.id,
                start_offset=start_offset,
                end_offset=start_offset + len(_QUOTED_SENTENCE),
                content_hash=passage.content_hash,
                quote=_QUOTED_SENTENCE,
            )
        )

        trace = RetrievalTrace(
            workspace_id=workspace_id,
            request_id="t027-seed",
            normalized_question="When was authentication postponed?",
        )
        session.add(trace)
        session.add(Conversation(id=conversation_id, workspace_id=workspace_id, title="Auth"))
        await session.flush()
        session.add(
            ConversationMessage(
                conversation_id=conversation_id,
                trace_id=trace.id,
                turn_number=1,
                question="When was authentication postponed?",
                response=QuestionResponse(
                    answer="After the import flow stabilised.",
                    state=AnswerState.ANSWERED,
                    confidence=ConfidenceCategory.HIGH,
                    trace_id=trace.id,
                ).model_dump(mode="json"),
                response_schema_version=1,
                knowledge_revision=1,
                created_at=datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
            )
        )
        await session.commit()
        return {
            "workspace_id": workspace_id,
            "document_id": document_id,
            "conversation_id": conversation_id,
            "upload_directory": upload_directory,
            "decision_id": decision.id,
            "version_id": result.version_id,
            "owner": owner,
        }


async def _reads(client: httpx.AsyncClient, seed: dict) -> dict:
    workspace_id = seed["workspace_id"]
    decisions = await client.get(f"/api/v1/workspaces/{workspace_id}/decisions")
    conversations = await client.get(f"/api/v1/workspaces/{workspace_id}/conversations")
    conversation = await client.get(
        f"/api/v1/workspaces/{workspace_id}/conversations/{seed['conversation_id']}"
    )
    assert decisions.status_code == 200, decisions.text
    assert conversations.status_code == 200, conversations.text
    assert conversation.status_code == 200, conversation.text
    return {
        "decisions": decisions.json(),
        "conversations": conversations.json(),
        "conversation": conversation.json(),
    }


@pytest.mark.asyncio
async def test_upgrade_rebuild_reports_progress_and_keeps_reads_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seed = await _seed(factory, tmp_path)
    workspace_id = seed["workspace_id"]

    # The corpus was ingested on the default preset, so configuring a different
    # one is what makes the startup scan see `corpus_reset_required`.
    settings = Settings(
        auth_jwt_secret="test-signing-secret-for-lifespan-tests",
        upload_directory=seed["upload_directory"],
        chunking_profile_preset="compact",
    )
    app = create_app(settings)
    started = asyncio.Event()
    release = asyncio.Event()
    app.state.provider_bundle_factory = _FakeBundleFactory(started, release)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: seed["owner"]
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=workspace_id)
    )
    # The test database is already at head; skip the backup gate rather than
    # writing an archive into the repo (same shortcut as test_app.py).
    monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

    statuses: list[str] = []
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            baseline = _normalized(await _reads(client, seed))
            async with app.router.lifespan_context(app):
                tasks = [
                    task
                    for task in app.state.startup_redispatch_tasks
                    if not task.done()
                ]
                loop = asyncio.get_running_loop()
                deadline = loop.time() + _POLL_TIMEOUT_SECONDS
                while True:
                    response = await client.get(
                        f"/api/v1/workspaces/{workspace_id}/corpus-rebuild"
                    )
                    if response.status_code == 200:
                        status = response.json()["status"]
                        statuses.append(status)
                    else:
                        # The dispatch is a background task: until it has
                        # committed its first row the endpoint answers 404
                        # `corpus_rebuild_not_found` (the documented contract
                        # for "no rebuild has run yet"). Reads must be stable
                        # in that window too, so it is polled, not skipped.
                        assert response.status_code == 404, response.text
                        assert response.json()["code"] == "corpus_rebuild_not_found"
                        status = "not_started"
                    statuses.append(status)
                    assert _normalized(await _reads(client, seed)) == baseline, (
                        "reads changed during a rebuild (V108): "
                        f"status {status!r}, statuses {statuses}"
                    )
                    if status == "running":
                        # Release only once `running` has been polled *and* the
                        # reads of that same poll verified stable, so the
                        # rebuild is genuinely in flight for that check.
                        release.set()
                    if status in {"completed", "failed"}:
                        break
                    assert loop.time() < deadline, f"rebuild never finished: {statuses}"
                    await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                if tasks:
                    await asyncio.gather(*tasks)

            assert statuses[-1] == "completed", statuses
            assert "running" in statuses, statuses
            # `not_started` entries are the 404 window before the dispatch task
            # commits its first row; they are kept in `statuses` so the window
            # is visible in a failure message, but the *rebuild's* first
            # observed status must be pending or running.
            observed = [status for status in statuses if status != "not_started"]
            assert observed[0] in {"pending", "running"}, statuses
            assert started.is_set(), "the rebuild never reached re-ingestion"

        async with factory() as session:
            rebuild = await session.scalar(
                select(CorpusRebuild).where(CorpusRebuild.workspace_id == workspace_id)
            )
            assert rebuild is not None
            assert rebuild.status == "completed"
            assert (rebuild.documents_total, rebuild.documents_completed) == (1, 1)
            assert rebuild.error is None

            document = await session.get(Document, seed["document_id"])
            assert document is not None
            assert document.active_version_id is not None
            assert document.active_version_id != seed["version_id"]

            # The decision survived the rebuild and was re-linked to the new
            # corpus rather than left stale (DB40/T031).
            decision = await session.get(Decision, seed["decision_id"])
            assert decision is not None
            assert decision.document_version_id == document.active_version_id
            evidence = await session.scalar(
                select(DecisionEvidence).where(
                    DecisionEvidence.decision_id == seed["decision_id"]
                )
            )
            assert evidence is not None
            assert evidence.passage_id is not None
            assert evidence.citation_stale is False
            assert evidence.quote == _QUOTED_SENTENCE
            passage = await session.get(Passage, evidence.passage_id)
            assert passage is not None
            assert passage.content[evidence.start_offset : evidence.end_offset] == (
                _QUOTED_SENTENCE
            )
    finally:
        release.set()
        async with factory() as cleanup:
            await cleanup.execute(
                delete(Workspace).where(Workspace.id == workspace_id)
            )
            await cleanup.execute(
                delete(User).where(User.id == seed["owner"].id)
            )
            await cleanup.commit()
        await engine.dispose()
