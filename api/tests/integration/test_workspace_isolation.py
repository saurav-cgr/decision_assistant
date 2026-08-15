"""Cross-workspace isolation: identical data in two workspaces must not leak."""

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.config import Settings
from decision_assistant.decisions.service import DecisionService
from decision_assistant.documents.service import DocumentService
from decision_assistant.evaluation.service import EvaluationService
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    Document,
    DocumentVersion,
    Passage,
    Workspace,
)
from decision_assistant.providers.base import EmbeddingPurpose
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.retrieval.service import HybridRetrievalService
from decision_assistant.timelines.service import TimelineService

EMBEDDING_PROFILE = FakeEmbeddingProvider(dimension=768).profile.as_dict()

SHARED_NAME = "authentication.md"
SHARED_TOPIC = "authentication"
SHARED_CONTENT = (
    "The team proposed postponing the authentication rollout until "
    "imports stabilize."
)


async def _seed_workspace(
    session: AsyncSession,
    *,
    name: str,
) -> tuple[Workspace, Document, Decision]:
    workspace = Workspace(name=name, embedding_profile=EMBEDDING_PROFILE)
    session.add(workspace)
    await session.flush()

    document = Document(
        workspace_id=workspace.id,
        display_name=SHARED_NAME,
        media_type="text/markdown",
    )
    session.add(document)
    await session.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        title="Authentication review",
        document_date=date(2026, 7, 15),
        participants=["Elena", "Maya"],
        source_type="meeting",
        project="Atlas",
        checksum=sha256(SHARED_CONTENT.encode()).hexdigest(),
        storage_path=f"/tmp/{name}-auth.md",
        normalized_content=SHARED_CONTENT,
        chunking_profile=CURRENT_CHUNKING_PROFILE,
        state="active",
    )
    session.add(version)
    await session.flush()
    document.active_version_id = version.id

    _embedding = (
        await FakeEmbeddingProvider(dimension=768).embed(
            [SHARED_CONTENT], purpose=EmbeddingPurpose.DOCUMENT
        )
    )[0]
    passage = Passage(
        document_version_id=version.id,
        sequence_number=0,
        content=SHARED_CONTENT,
        start_offset=0,
        end_offset=len(SHARED_CONTENT),
        content_hash=sha256(SHARED_CONTENT.encode()).hexdigest(),
        locator={"kind": "lines", "start": 1, "end": 1},
        embedding=_embedding,
        embedding_profile=EMBEDDING_PROFILE,
    )
    session.add(passage)
    await session.flush()

    decision = Decision(
        document_version_id=version.id,
        statement=f"{name} decision: postpone authentication.",
        effective_date=date(2026, 7, 15),
        owner="Elena",
        status="proposed",
        reasons=["Imports unstable"],
        alternatives=[],
        project="Atlas",
        topic=SHARED_TOPIC,
        extraction_confidence=0.9,
        provenance="extracted",
        review_state="supported",
        user_edited=False,
        retired=False,
    )
    session.add(decision)
    await session.flush()
    statement_quote = "postponing the authentication rollout"
    session.add(
        DecisionEvidence(
            decision_id=decision.id,
            passage_id=passage.id,
            field_name="statement",
            start_offset=SHARED_CONTENT.index(statement_quote),
            end_offset=SHARED_CONTENT.index(statement_quote) + len(statement_quote),
            support_state="supported",
            is_primary=True,
            content_hash=passage.content_hash,
        )
    )
    await session.flush()
    return workspace, document, decision


async def test_identical_documents_and_decisions_do_not_leak(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    ws_a, doc_a, decision_a = await _seed_workspace(
        db_session, name=f"A {uuid4()}"
    )
    ws_b, doc_b, decision_b = await _seed_workspace(
        db_session, name=f"B {uuid4()}"
    )
    assert doc_a.display_name == doc_b.display_name
    assert decision_a.topic == decision_b.topic

    document_service = DocumentService(
        session=db_session,
        settings=Settings(upload_directory=tmp_path / "uploads"),
        dispatcher=None,  # type: ignore[arg-type]
    )
    docs_a = (await document_service.list_documents(workspace_id=ws_a.id)).items
    docs_b = (await document_service.list_documents(workspace_id=ws_b.id)).items
    assert [d.id for d in docs_a] == [doc_a.id]
    assert [d.id for d in docs_b] == [doc_b.id]

    decision_service = DecisionService(db_session)
    decisions_a = (
        await decision_service.list_decisions(workspace_id=ws_a.id)
    ).items
    decisions_b = (
        await decision_service.list_decisions(workspace_id=ws_b.id)
    ).items
    assert [d.id for d in decisions_a] == [decision_a.id]
    assert [d.id for d in decisions_b] == [decision_b.id]


async def test_timelines_are_workspace_scoped(
    db_session: AsyncSession,
) -> None:
    ws_a, _, decision_a = await _seed_workspace(db_session, name=f"A {uuid4()}")
    ws_b, _, decision_b = await _seed_workspace(db_session, name=f"B {uuid4()}")

    timeline_service = TimelineService(db_session)
    timeline_a = await timeline_service.build_timeline(
        SHARED_TOPIC, workspace_id=ws_a.id
    )
    timeline_b = await timeline_service.build_timeline(
        SHARED_TOPIC, workspace_id=ws_b.id
    )

    assert [e.decision_id for e in timeline_a.entries] == [
        decision_a.id
    ]
    assert [e.decision_id for e in timeline_b.entries] == [
        decision_b.id
    ]


async def test_retrieval_traces_are_workspace_scoped(
    db_session: AsyncSession,
) -> None:
    ws_a, _, _ = await _seed_workspace(db_session, name=f"A {uuid4()}")
    ws_b, _, _ = await _seed_workspace(db_session, name=f"B {uuid4()}")
    embedding = FakeEmbeddingProvider(dimension=768)

    async def search(workspace_id):
        return await HybridRetrievalService(
            session=db_session, embedding_provider=embedding
        ).search(
            __import__(
                "decision_assistant.retrieval.schemas",
                fromlist=["RetrievalSearchRequest"],
            ).RetrievalSearchRequest(question=SHARED_TOPIC),
            request_id=f"iso-{workspace_id}",
            workspace_id=workspace_id,
        )

    response_a = await search(ws_a.id)
    response_b = await search(ws_b.id)
    passage_ids_a = {str(r.passage_id) for r in response_a.results}
    passage_ids_b = {str(r.passage_id) for r in response_b.results}
    assert passage_ids_a.isdisjoint(passage_ids_b)


async def test_evaluation_runs_are_workspace_scoped(
    db_session: AsyncSession,
    tmp_path,
) -> None:
    ws_a, _, _ = await _seed_workspace(db_session, name=f"A {uuid4()}")
    ws_b, _, _ = await _seed_workspace(db_session, name=f"B {uuid4()}")
    dataset_path = tmp_path / "questions.json"
    dataset_path.write_text(
        json.dumps(
            {
                "version": "decision-eval-v1",
                "questions": [
                    {
                        "external_id": "q1",
                        "question": "What happened to authentication?",
                        "expectation": "answer",
                        "expected_answer_summary": "postponed",
                        "expected_documents": [],
                        "expected_passages": [],
                        "tags": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = EvaluationService(
        session=db_session,
        dataset_path=dataset_path,
        executor=None,  # type: ignore[arg-type]
        judge=None,  # type: ignore[arg-type]
    )

    run_a = await service.create_run(
        _run_request(), workspace_id=ws_a.id
    )
    run_b = await service.create_run(
        _run_request(), workspace_id=ws_b.id
    )
    assert run_a.workspace_id == ws_a.id
    assert run_b.workspace_id == ws_b.id

    runs_a = await service.list_runs(workspace_id=ws_a.id)
    runs_b = await service.list_runs(workspace_id=ws_b.id)
    assert [r.id for r in runs_a] == [run_a.id]
    assert [r.id for r in runs_b] == [run_b.id]


def _run_request():
    from decision_assistant.evaluation.schemas import EvaluationRunRequest

    return EvaluationRunRequest(
        strategy="hybrid",
        dataset_version="decision-eval-v1",
        configuration={},
    )
