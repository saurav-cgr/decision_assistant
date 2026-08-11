from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.router import get_answer_service
from decision_assistant.answering.service import AnswerService
from decision_assistant.config import Settings
from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.documents.router import get_document_service
from decision_assistant.documents.service import DocumentService
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.main import create_app
from decision_assistant.models import IngestionJob, Passage, RetrievalTrace
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.retrieval.router import get_retrieval_service
from decision_assistant.retrieval.service import HybridRetrievalService


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def dispatch(
        self,
        *,
        document_id: UUID,
        job_id: UUID,
        source_path: Path,
        request_id: str,
    ) -> None:
        self.calls.append(
            {
                "document_id": document_id,
                "job_id": job_id,
                "source_path": source_path,
                "request_id": request_id,
            }
        )


@pytest.mark.asyncio
async def test_upload_index_ask_abstain_and_inspect_trace(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    settings = Settings(upload_directory=tmp_path / "uploads")
    dispatcher = RecordingDispatcher()
    document_service = DocumentService(
        session=db_session,
        settings=settings,
        dispatcher=dispatcher,
    )
    app = create_app(settings)
    app.dependency_overrides[get_document_service] = lambda: document_service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        source = Path("tests/fixtures/meeting.md").read_bytes()
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"files": ("meeting.md", source, "text/markdown")},
            headers={"x-request-id": "vertical-upload"},
        )

        assert upload.status_code == 202
        uploaded = upload.json()["results"][0]
        assert uploaded["status"] == "accepted"
        assert len(dispatcher.calls) == 1

        embedding_provider = FakeEmbeddingProvider(dimension=768)
        metadata_provider = FakeGenerationProvider(
            [
                {
                    "title": "Architecture Sync",
                    "document_date": "2026-07-15",
                    "participants": ["Maya", "Ravi", "Elena"],
                    "source_type": "meeting",
                    "project": "Atlas",
                }
            ]
        )
        decision_provider = FakeGenerationProvider([{"decisions": []}])
        ingestion_service = IngestionService(
            session=db_session,
            embedding_provider=embedding_provider,
            decision_extractor=DecisionExtractor(decision_provider),
            metadata_extractor=MetadataExtractor(metadata_provider),
            upload_directory=settings.upload_directory,
        )
        dispatch = dispatcher.calls[0]
        await ingestion_service.ingest(
            dispatch["document_id"],
            dispatch["source_path"],
            request_id=dispatch["request_id"],
            job_id=dispatch["job_id"],
        )

        job = await db_session.get(IngestionJob, UUID(uploaded["job_id"]))
        assert job is not None
        assert (job.status, job.stage, job.progress) == (
            "completed",
            "completed",
            100,
        )
        passage = await db_session.scalar(
            select(Passage).where(Passage.document_version_id == job.document_version_id)
        )
        assert passage is not None
        quote = "The team proposed postponing authentication"
        quote_start = passage.content.index(quote)

        answer_provider = FakeGenerationProvider(
            [
                {
                    "answer": "Authentication was proposed for postponement.",
                    "claims": [
                        {
                            "text": "Authentication was proposed for postponement.",
                            "central": True,
                            "passage_ids": [str(passage.id)],
                        }
                    ],
                    "citations": [
                        {
                            "passage_id": str(passage.id),
                            "quote": quote,
                            "start_offset": quote_start,
                            "end_offset": quote_start + len(quote),
                            "content_hash": sha256(
                                passage.content.encode()
                            ).hexdigest(),
                        }
                    ],
                    "conflicts": [],
                    "unsupported_facets": [],
                    "confidence": "high",
                },
                {
                    "answer": "Insufficient evidence to answer that question.",
                    "claims": [],
                    "citations": [],
                    "conflicts": [],
                    "unsupported_facets": ["database encryption owner"],
                    "confidence": "none",
                },
            ]
        )
        retrieval_service = HybridRetrievalService(
            session=db_session,
            embedding_provider=embedding_provider,
        )
        answer_service = AnswerService(
            session=db_session,
            retrieval_service=retrieval_service,
            generation_provider=answer_provider,
        )
        app.dependency_overrides[get_answer_service] = lambda: answer_service
        app.dependency_overrides[get_retrieval_service] = lambda: retrieval_service

        supported = await client.post(
            "/api/v1/questions",
            json={"question": "What happened to authentication?"},
            headers={"x-request-id": "vertical-supported"},
        )
        unsupported = await client.post(
            "/api/v1/questions",
            json={"question": "Who owns database encryption?"},
            headers={"x-request-id": "vertical-unsupported"},
        )

        assert supported.status_code == 200
        assert supported.json()["state"] == "answered"
        assert supported.json()["citations"][0]["quote"] == quote
        assert supported.json()["citations"][0]["document_id"] == str(
            dispatch["document_id"]
        )
        assert supported.json()["citations"][0]["document_name"] == "meeting.md"
        assert supported.json()["citations"][0]["locator"] == passage.locator
        assert unsupported.status_code == 200
        assert unsupported.json()["state"] == "abstained"
        assert unsupported.json()["citations"] == []

        trace_id = supported.json()["trace_id"]
        trace_response = await client.get(f"/api/v1/retrieval-traces/{trace_id}")

        assert trace_response.status_code == 200
        assert trace_response.json()["request_id"] == "vertical-supported"
        trace = await db_session.get(RetrievalTrace, UUID(trace_id))
        assert trace is not None
        assert str(passage.id) in trace.selected_passage_ids
