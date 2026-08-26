from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.db import get_session
from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.main import create_app
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    DecisionRelation,
    DecisionRevision,
    Document,
    DocumentVersion,
    EmbeddingCache,
    Passage,
    Workspace,
)
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.workspace.context import WorkspaceContext, get_workspace_context
from decision_assistant.workspace.embedding_profile import embedding_profile_fingerprint

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


@pytest.mark.asyncio
async def test_list_filters_decisions_and_detail_includes_evidence_history(
    decisions_api: DecisionApiHarness,
) -> None:
    response = await decisions_api.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions",
        params={
            "status": "active",
            "owner": "Elena",
            "project": "Atlas",
            "topic": "authentication",
            "review_state": "supported",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        str(decisions_api.earlier_decision.id)
    ]

    detail = await decisions_api.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.earlier_decision.id}"
    )

    assert detail.status_code == 200
    payload = detail.json()
    assert payload["statement"] == "Postpone authentication until imports stabilize."
    assert payload["review_state"] == "supported"
    assert {item["field_name"] for item in payload["evidence"]} == {
        "statement",
        "owner",
    }
    assert payload["revisions"] == []
    assert payload["relations"] == []


@pytest.mark.asyncio
async def test_supported_correction_replaces_field_evidence_and_records_revision(
    decisions_api: DecisionApiHarness,
) -> None:
    original_source = decisions_api.active_passage.content
    quote = "Maya owns the migration decision."

    response = await decisions_api.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.earlier_decision.id}",
        json={
            "changes": [
                supported_change(
                    "owner",
                    "Maya",
                    decisions_api.active_passage,
                    quote,
                )
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["owner"] == "Maya"
    assert response.json()["provenance"] == "user_corrected"
    assert response.json()["review_state"] == "supported"

    revision = await decisions_api.session.scalar(
        select(DecisionRevision).where(
            DecisionRevision.decision_id == decisions_api.earlier_decision.id,
            DecisionRevision.field_name == "owner",
        )
    )
    assert revision is not None
    assert revision.old_value == "Elena"
    assert revision.new_value == "Maya"
    assert revision.evidence_passage_ids == [decisions_api.active_passage.id]
    assert revision.support_state == "supported"

    owner_evidence = list(
        await decisions_api.session.scalars(
            select(DecisionEvidence).where(
                DecisionEvidence.decision_id == decisions_api.earlier_decision.id,
                DecisionEvidence.field_name == "owner",
            )
        )
    )
    assert len(owner_evidence) == 1
    assert owner_evidence[0].start_offset == original_source.index(quote)
    await decisions_api.session.refresh(decisions_api.active_passage)
    assert decisions_api.active_passage.content == original_source
    workspace = await decisions_api.session.get(Workspace, WORKSPACE_ID)
    assert workspace is not None
    await decisions_api.session.refresh(workspace)
    assert workspace.knowledge_revision == 2


@pytest.mark.asyncio
async def test_correction_without_evidence_is_saved_as_unsupported(
    decisions_api: DecisionApiHarness,
) -> None:
    response = await decisions_api.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.earlier_decision.id}",
        json={
            "changes": [
                {
                    "field_name": "reasons",
                    "value": ["Schedule pressure"],
                    "support_state": "unsupported",
                    "evidence": [],
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["reasons"] == ["Schedule pressure"]
    assert response.json()["review_state"] == "unsupported"
    assert response.json()["user_edited"] is True
    revision = await decisions_api.session.scalar(
        select(DecisionRevision).where(
            DecisionRevision.decision_id == decisions_api.earlier_decision.id,
            DecisionRevision.field_name == "reasons",
        )
    )
    assert revision is not None
    assert revision.evidence_passage_ids == []
    assert revision.support_state == "unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("evidence_kind", "expected_code"),
    [
        ("retired", "inactive_evidence"),
        ("stale_hash", "stale_evidence"),
    ],
)
async def test_correction_rejects_retired_or_stale_evidence(
    decisions_api: DecisionApiHarness,
    evidence_kind: str,
    expected_code: str,
) -> None:
    if evidence_kind == "retired":
        evidence = evidence_payload(
            decisions_api.retired_passage,
            "authentication to Ravi",
        )
    else:
        evidence = evidence_payload(
            decisions_api.active_passage,
            "Maya owns the migration decision.",
        )
        evidence["content_hash"] = "0" * 64

    response = await decisions_api.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.earlier_decision.id}",
        json={
            "changes": [
                {
                    "field_name": "owner",
                    "value": "Maya",
                    "support_state": "supported",
                    "evidence": [evidence],
                }
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == expected_code
    await decisions_api.session.refresh(decisions_api.earlier_decision)
    assert decisions_api.earlier_decision.owner == "Elena"


@pytest.mark.asyncio
async def test_user_can_create_explicit_supersedes_relation(
    decisions_api: DecisionApiHarness,
) -> None:
    rationale = "Team confirmed authentication work replaces the postponement."
    response = await decisions_api.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.later_decision.id}/relations",
        json={
            "target_decision_id": str(decisions_api.earlier_decision.id),
            "relation_type": "supersedes",
            "rationale": rationale,
        },
    )

    assert response.status_code == 201
    relation_payload = response.json()
    assert relation_payload["source_decision_id"] == str(
        decisions_api.later_decision.id
    )
    assert relation_payload["target_decision_id"] == str(
        decisions_api.earlier_decision.id
    )
    assert relation_payload["relation_type"] == "supersedes"
    assert relation_payload["authority"] == "user_confirmed"
    assert relation_payload["rationale"] == rationale
    assert "evidence" not in relation_payload
    assert "citation" not in relation_payload
    assert "quote" not in relation_payload
    relation = await decisions_api.session.scalar(
        select(DecisionRelation).where(
            DecisionRelation.source_decision_id == decisions_api.later_decision.id,
            DecisionRelation.target_decision_id == decisions_api.earlier_decision.id,
        )
    )
    assert relation is not None
    assert relation.authority == "user_confirmed"
    assert relation.confidence is None
    assert relation.rationale == rationale

    detail = await decisions_api.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.later_decision.id}"
    )
    assert detail.status_code == 200
    stored_relation = detail.json()["relations"][0]
    assert stored_relation["authority"] == "user_confirmed"
    assert stored_relation["rationale"] == rationale
    assert "evidence" not in stored_relation
    assert "citation" not in stored_relation
    assert "quote" not in stored_relation


@pytest.mark.asyncio
async def test_reindex_moves_user_correction_to_needs_review(
    decisions_api: DecisionApiHarness,
    tmp_path: Path,
) -> None:
    correction = await decisions_api.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.earlier_decision.id}",
        json={
            "changes": [
                supported_change(
                    "owner",
                    "Maya",
                    decisions_api.active_passage,
                    "Maya owns the migration decision.",
                )
            ]
        },
    )
    assert correction.status_code == 200

    source = tmp_path / "architecture.md"
    source.write_text(
        "# Authentication\n\nMaya started authentication after import migration.\n",
        encoding="utf-8",
    )
    service = IngestionService(
        session=decisions_api.session,
        embedding_provider=FakeEmbeddingProvider(dimension=768),
        decision_extractor=DecisionExtractor(
            FakeGenerationProvider([{"decisions": []}] * 10)
        ),
        metadata_extractor=MetadataExtractor(
            FakeGenerationProvider(
                [
                    {
                        "document_date": None,
                        "participants": [],
                        "project": "Atlas",
                        "source_type": "meeting",
                    }
                ]
            )
        ),
        upload_directory=tmp_path / "uploads",
    )

    await service.ingest(
        decisions_api.document.id,
        source,
        request_id="reindex-after-correction",
    )

    detail = await decisions_api.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/decisions/{decisions_api.earlier_decision.id}"
    )
    assert detail.status_code == 200
    assert detail.json()["review_state"] == "needs_review"
    assert detail.json()["retired"] is False
