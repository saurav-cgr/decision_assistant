from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.db import get_session
from decision_assistant.main import create_app
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    DecisionRelation,
    Document,
    DocumentVersion,
    Passage,
    Workspace,
)
from decision_assistant.workspace.context import WorkspaceContext, get_workspace_context

WORKSPACE_ID = UUID("55555555-5555-5555-5555-555555555555")


@dataclass(slots=True)
class TimelineHarness:
    client: httpx.AsyncClient
    proposed_id: UUID
    accepted_id: UUID
    possible_revision_id: UUID
    undated_id: UUID
    unsupported_id: UUID
    needs_review_id: UUID
    evidence_less_id: UUID


async def add_decision_with_evidence(
    session: AsyncSession,
    *,
    version: DocumentVersion,
    sequence_number: int,
    statement: str,
    effective_date: date | None,
    status: str,
    topic: str,
    review_state: str = "supported",
    created_at: datetime,
    with_evidence: bool = True,
) -> Decision:
    passage = Passage(
        document_version_id=version.id,
        sequence_number=sequence_number,
        content=statement,
        start_offset=0,
        end_offset=len(statement),
        content_hash=sha256(statement.encode()).hexdigest(),
        locator={
            "kind": "lines",
            "start": sequence_number + 1,
            "end": sequence_number + 1,
        },
        embedding=[0.0] * 768,
        created_at=created_at,
        updated_at=created_at,
    )
    decision = Decision(
        document_version_id=version.id,
        statement=statement,
        effective_date=effective_date,
        owner="Maya",
        status=status,
        reasons=[],
        alternatives=[],
        project="Atlas",
        topic=topic,
        extraction_confidence=0.9,
        provenance=(
            "user_corrected" if review_state != "supported" else "extracted"
        ),
        review_state=review_state,
        user_edited=review_state != "supported",
        retired=False,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add_all([passage, decision])
    await session.flush()
    if with_evidence:
        session.add(
            DecisionEvidence(
                decision_id=decision.id,
                passage_id=passage.id,
                field_name="statement",
                start_offset=0,
                end_offset=len(statement),
                support_state=review_state,
                is_primary=True,
                content_hash=passage.content_hash,
                created_at=created_at,
            )
        )
        await session.flush()
    return decision


@pytest_asyncio.fixture
async def timelines_api(
    db_session: AsyncSession,
) -> AsyncIterator[TimelineHarness]:
    workspace = Workspace(
        id=WORKSPACE_ID,
        name=f"Timeline workspace {uuid4()}",
        embedding_profile={"provider": "fake", "dimension": 768},
    )
    db_session.add(workspace)
    await db_session.flush()

    dated_document = Document(
        workspace_id=workspace.id,
        display_name="authentication.md",
        media_type="text/markdown",
    )
    undated_document = Document(
        workspace_id=workspace.id,
        display_name="follow-up.txt",
        media_type="text/plain",
    )
    db_session.add_all([dated_document, undated_document])
    await db_session.flush()

    dated_version = DocumentVersion(
        document_id=dated_document.id,
        version_number=1,
        title="Authentication meeting",
        document_date=date(2026, 7, 15),
        participants=["Maya"],
        source_type="meeting",
        project="Atlas",
        checksum="a" * 64,
        storage_path="/tmp/authentication.md",
        normalized_content="Authentication decisions",
        state="active",
    )
    undated_version = DocumentVersion(
        document_id=undated_document.id,
        version_number=1,
        title="Follow-up",
        document_date=None,
        participants=["Maya"],
        source_type="note",
        project="Atlas",
        checksum="b" * 64,
        storage_path="/tmp/follow-up.txt",
        normalized_content="Undated follow-up",
        state="active",
    )
    db_session.add_all([dated_version, undated_version])
    await db_session.flush()
    dated_document.active_version_id = dated_version.id
    undated_document.active_version_id = undated_version.id

    proposed = await add_decision_with_evidence(
        db_session,
        version=dated_version,
        sequence_number=0,
        statement="Authentication was proposed for postponement.",
        effective_date=date(2026, 7, 10),
        status="proposed",
        topic="Authentication",
        created_at=datetime(2026, 7, 10, 9, tzinfo=timezone.utc),
    )
    accepted = await add_decision_with_evidence(
        db_session,
        version=dated_version,
        sequence_number=1,
        statement="Authentication postponement was accepted.",
        effective_date=None,
        status="active",
        topic="authentication",
        created_at=datetime(2026, 7, 15, 9, tzinfo=timezone.utc),
    )
    possible_revision = await add_decision_with_evidence(
        db_session,
        version=dated_version,
        sequence_number=2,
        statement="Authentication implementation may begin after migration.",
        effective_date=date(2026, 7, 20),
        status="proposed",
        topic="identity",
        created_at=datetime(2026, 7, 20, 9, tzinfo=timezone.utc),
    )
    undated = await add_decision_with_evidence(
        db_session,
        version=undated_version,
        sequence_number=0,
        statement="Authentication rollout remains under discussion.",
        effective_date=None,
        status="proposed",
        topic="authentication",
        created_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
    )
    unsupported = await add_decision_with_evidence(
        db_session,
        version=dated_version,
        sequence_number=3,
        statement="Authentication owner changed without evidence.",
        effective_date=date(2026, 7, 17),
        status="active",
        topic="authentication",
        review_state="unsupported",
        created_at=datetime(2026, 7, 17, 9, tzinfo=timezone.utc),
    )
    needs_review = await add_decision_with_evidence(
        db_session,
        version=dated_version,
        sequence_number=4,
        statement="Authentication plan needs evidence review.",
        effective_date=date(2026, 7, 18),
        status="active",
        topic="authentication",
        review_state="needs_review",
        created_at=datetime(2026, 7, 18, 9, tzinfo=timezone.utc),
    )
    evidence_less = await add_decision_with_evidence(
        db_session,
        version=dated_version,
        sequence_number=5,
        statement="Authentication has no citable source span.",
        effective_date=date(2026, 7, 19),
        status="active",
        topic="authentication",
        created_at=datetime(2026, 7, 19, 9, tzinfo=timezone.utc),
        with_evidence=False,
    )

    db_session.add_all(
        [
            DecisionRelation(
                source_decision_id=accepted.id,
                target_decision_id=proposed.id,
                relation_type="supersedes",
                authority="user_confirmed",
                confidence=None,
                rationale="Team confirmed the acceptance replaced the proposal.",
            ),
            DecisionRelation(
                source_decision_id=possible_revision.id,
                target_decision_id=accepted.id,
                relation_type="revises",
                authority="model_inferred",
                confidence="high",
                rationale="Similar topic and later date.",
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
        yield TimelineHarness(
            client=client,
            proposed_id=proposed.id,
            accepted_id=accepted.id,
            possible_revision_id=possible_revision.id,
            undated_id=undated.id,
            unsupported_id=unsupported.id,
            needs_review_id=needs_review.id,
            evidence_less_id=evidence_less.id,
        )


@pytest.mark.asyncio
async def test_timeline_is_cited_ordered_and_expands_relationships(
    timelines_api: TimelineHarness,
) -> None:
    response = await timelines_api.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/timelines",
        params={"topic": "  AUTHENTICATION  "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["topic"] == "authentication"
    entries = payload["entries"]
    assert [entry["decision_id"] for entry in entries] == [
        str(timelines_api.proposed_id),
        str(timelines_api.accepted_id),
        str(timelines_api.possible_revision_id),
        str(timelines_api.undated_id),
    ]

    proposed, accepted, possible_revision, undated = entries
    assert proposed["effective_date"] == "2026-07-10"
    assert proposed["display_date"] == "2026-07-10"
    assert proposed["date_is_fallback"] is False
    assert accepted["effective_date"] is None
    assert accepted["display_date"] == "2026-07-15"
    assert accepted["date_is_fallback"] is True
    assert possible_revision["display_date"] == "2026-07-20"
    assert undated["display_date"] is None
    assert undated["date_is_fallback"] is False

    assert proposed["original_status"] == "proposed"
    assert proposed["display_status"] == "superseded"
    assert accepted["original_status"] == "active"
    assert accepted["display_status"] == "active"
    confirmed_relation = accepted["relationships"][0]
    assert confirmed_relation["label"] == "supersedes"
    assert confirmed_relation["authority"] == "user_confirmed"

    inferred_relation = possible_revision["relationships"][0]
    assert inferred_relation["relation_type"] == "revises"
    assert inferred_relation["label"] == "possible_revision"
    assert inferred_relation["authority"] == "model_inferred"
    assert accepted["display_status"] == "active"

    for entry in entries:
        assert entry["evidence"]
        citation = entry["evidence"][0]
        assert citation["quote"] == entry["statement"]
        assert citation["passage_id"]
        assert citation["content_hash"]

    returned_ids = {entry["decision_id"] for entry in entries}
    assert str(timelines_api.unsupported_id) not in returned_ids
    assert str(timelines_api.needs_review_id) not in returned_ids
    assert str(timelines_api.evidence_less_id) not in returned_ids
