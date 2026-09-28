"""Decisions API: listing, detail, corrections, relations and reindex review.

The workspace/document/passage/decision scaffolding lives in
`tests/support/decision_api_fixtures.py` so this module stays under AGENTS.md's 500-line cap
(DB53; the same extraction DB30 and DB49 used).
"""

from pathlib import Path

import pytest
from sqlalchemy import select

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.decisions.models import (
    DecisionEvidence,
    DecisionRelation,
    DecisionRevision,
)
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.workspace.models import Workspace
from tests.support.decision_api_fixtures import (
    WORKSPACE_ID,
    DecisionApiHarness,
    evidence_payload,
    supported_change,
)
from tests.support.decision_api_fixtures import decisions_api as decisions_api



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
