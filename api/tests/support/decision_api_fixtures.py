"""Shared harness for `test_decisions_api.py` (DB53).

Extracted so the test module stays under AGENTS.md's 500-line cap for hand-written files; DB30 and
DB49 set the same precedent (`tests/support/`). The test module re-exports `decisions_api` (the suite
runs with `--import-mode=importlib`, so the fixture has to be a module-level name there), and the
payload helpers stay plain functions because each test builds its own bodies.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.db import get_session
from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    EmbeddingCache,
    Passage,
)
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.main import create_app
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.workspace.context import WorkspaceContext, get_workspace_context
from decision_assistant.workspace.embedding_profile import embedding_profile_fingerprint
from decision_assistant.workspace.models import Workspace

FAKE_EMBEDDING_PROFILE = FakeEmbeddingProvider(dimension=768).profile.as_dict()

WORKSPACE_ID = UUID("22222222-2222-2222-2222-222222222222")


@dataclass(slots=True)
class DecisionApiHarness:
    client: httpx.AsyncClient
    session: AsyncSession
    document: Document
    active_version: DocumentVersion
    retired_version: DocumentVersion
    active_passage: Passage
    retired_passage: Passage
    earlier_decision: Decision
    later_decision: Decision


def evidence_payload(passage: Passage, quote: str) -> dict[str, object]:
    start = passage.content.index(quote)
    return {
        "passage_id": str(passage.id),
        "start_offset": start,
        "end_offset": start + len(quote),
        "content_hash": passage.content_hash,
    }


def supported_change(
    field_name: str,
    value: object,
    passage: Passage,
    quote: str,
) -> dict[str, object]:
    return {
        "field_name": field_name,
        "value": value,
        "support_state": "supported",
        "evidence": [evidence_payload(passage, quote)],
    }


@pytest_asyncio.fixture
async def decisions_api(
    db_session: AsyncSession,
) -> AsyncIterator[DecisionApiHarness]:
    workspace = Workspace(
        id=WORKSPACE_ID,
        name=f"Decision API workspace {uuid4()}",
        embedding_profile=FAKE_EMBEDDING_PROFILE,
    )
    db_session.add(workspace)
    await db_session.flush()

    document = Document(
        workspace_id=workspace.id,
        display_name="architecture.md",
        media_type="text/markdown",
    )
    db_session.add(document)
    await db_session.flush()

    active_content = (
        "Elena proposed postponing authentication. "
        "Maya owns the migration decision."
    )
    retired_content = "The retired note assigned authentication to Ravi."
    active_version = DocumentVersion(
        document_id=document.id,
        version_number=2,
        title="Architecture review",
        document_date=date(2026, 7, 15),
        participants=["Elena", "Maya"],
        source_type="meeting",
        project="Atlas",
        checksum=sha256(active_content.encode()).hexdigest(),
        storage_path="/tmp/architecture-v2.md",
        normalized_content=active_content,
        chunking_profile=CURRENT_CHUNKING_PROFILE,
        state="active",
    )
    retired_version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        title="Old architecture review",
        document_date=date(2026, 7, 1),
        participants=["Ravi"],
        source_type="meeting",
        project="Atlas",
        checksum=sha256(retired_content.encode()).hexdigest(),
        storage_path="/tmp/architecture-v1.md",
        normalized_content=retired_content,
        chunking_profile=CURRENT_CHUNKING_PROFILE,
        state="retired",
    )
    db_session.add_all([active_version, retired_version])
    await db_session.flush()
    document.active_version_id = active_version.id

    active_passage = Passage(
        document_version_id=active_version.id,
        sequence_number=0,
        content=active_content,
        start_offset=0,
        end_offset=len(active_content),
        content_hash=sha256(active_content.encode()).hexdigest(),
        locator={"kind": "lines", "start": 1, "end": 1},
        embedding=[0.0] * 768,
        embedding_profile=FAKE_EMBEDDING_PROFILE,
    )
    retired_passage = Passage(
        document_version_id=retired_version.id,
        sequence_number=0,
        content=retired_content,
        start_offset=0,
        end_offset=len(retired_content),
        content_hash=sha256(retired_content.encode()).hexdigest(),
        locator={"kind": "lines", "start": 1, "end": 1},
        embedding=[0.0] * 768,
        embedding_profile=FAKE_EMBEDDING_PROFILE,
    )
    db_session.add_all([active_passage, retired_passage])
    await db_session.flush()
    for passage in (active_passage, retired_passage):
        cache = EmbeddingCache(
            workspace_id=workspace.id,
            content_hash=passage.content_hash,
            embedding_profile_fingerprint=embedding_profile_fingerprint(
                FAKE_EMBEDDING_PROFILE
            ),
            embedding_profile=FAKE_EMBEDDING_PROFILE,
            embedding=passage.embedding,
        )
        db_session.add(cache)
        await db_session.flush()
        passage.embedding_cache_id = cache.id

    earlier_decision = Decision(
        workspace_id=WORKSPACE_ID,
        document_version_id=active_version.id,
        statement="Postpone authentication until imports stabilize.",
        effective_date=date(2026, 7, 15),
        owner="Elena",
        status="active",
        reasons=["Import flow is unstable"],
        alternatives=["Ship authentication first"],
        project="Atlas",
        topic="authentication",
        extraction_confidence=0.9,
        provenance="extracted",
        review_state="supported",
        user_edited=False,
        retired=False,
    )
    later_decision = Decision(
        workspace_id=WORKSPACE_ID,
        document_version_id=active_version.id,
        statement="Start authentication after import migration.",
        effective_date=date(2026, 8, 1),
        owner="Maya",
        status="proposed",
        reasons=["Migration is nearly complete"],
        alternatives=[],
        project="Atlas",
        topic="authentication",
        extraction_confidence=0.85,
        provenance="extracted",
        review_state="supported",
        user_edited=False,
        retired=False,
    )
    db_session.add_all([earlier_decision, later_decision])
    await db_session.flush()

    statement_quote = "Elena proposed postponing authentication."
    owner_quote = "Elena"
    db_session.add_all(
        [
            DecisionEvidence(
                decision_id=earlier_decision.id,
                passage_id=active_passage.id,
                field_name="statement",
                start_offset=active_content.index(statement_quote),
                end_offset=(
                    active_content.index(statement_quote) + len(statement_quote)
                ),
                support_state="supported",
                is_primary=True,
                content_hash=active_passage.content_hash,
            ),
            DecisionEvidence(
                decision_id=earlier_decision.id,
                passage_id=active_passage.id,
                field_name="owner",
                start_offset=active_content.index(owner_quote),
                end_offset=active_content.index(owner_quote) + len(owner_quote),
                support_state="supported",
                is_primary=True,
                content_hash=active_passage.content_hash,
            ),
        ]
    )
    await db_session.flush()

    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_workspace_context] = (
        lambda: WorkspaceContext(workspace_id=WORKSPACE_ID)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield DecisionApiHarness(
            client=client,
            session=db_session,
            document=document,
            active_version=active_version,
            retired_version=retired_version,
            active_passage=active_passage,
            retired_passage=retired_passage,
            earlier_decision=earlier_decision,
            later_decision=later_decision,
        )
