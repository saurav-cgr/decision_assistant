from dataclasses import asdict
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.schemas import AnswerState, QuestionRequest
from decision_assistant.answering.service import AnswerService
from decision_assistant.evaluation.models import EvaluationQuestion
from decision_assistant.evaluation.semantic_retrieval import SemanticRetrievalService
from decision_assistant.ingestion.models import Document, DocumentVersion, Passage
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.ingestion.retrieval_units import RetrievalUnitStrategy
from decision_assistant.providers.base import EmbeddingProvider, GenerationProvider
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.retrieval.reranking import GenerationReranker
from decision_assistant.retrieval.service import HybridRetrievalService, RetrievalConfig


class RuntimeEvaluationExecutor:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        generation_provider: GenerationProvider,
        chunking_profile: dict[str, object] | None = None,
        retrieval_unit_strategy: RetrievalUnitStrategy = "passage_hybrid",
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._generation_provider = generation_provider
        self._chunking_profile = (
            chunking_profile if chunking_profile is not None else CURRENT_CHUNKING_PROFILE
        )
        self._retrieval_unit_strategy = retrieval_unit_strategy

    @property
    def embedding_profile(self) -> dict[str, Any]:
        return asdict(self._embedding_provider.profile)

    @property
    def generation_profile(self) -> dict[str, Any]:
        return asdict(self._generation_provider.profile)

    async def execute(
        self,
        question: EvaluationQuestion,
        *,
        run_id: UUID,
        strategy: str,
        configuration: dict[str, Any],
        workspace_id: UUID,
    ) -> dict[str, Any]:
        started = perf_counter()
        top_k = int(configuration.get("top_k", 5))
        retrieval_service: Any
        if strategy == "semantic":
            retrieval_service = SemanticRetrievalService(
                session=self._session,
                embedding_provider=self._embedding_provider,
                top_k=top_k,
                chunking_profile=self._chunking_profile,
                retrieval_unit_strategy=self._retrieval_unit_strategy,
            )
        else:
            rerank_enabled = bool(configuration.get("rerank_enabled", False))
            reranker = (
                GenerationReranker(self._generation_provider)
                if rerank_enabled
                else None
            )
            retrieval_service = HybridRetrievalService(
                session=self._session,
                embedding_provider=self._embedding_provider,
                config=RetrievalConfig(
                    top_k=top_k,
                    rerank_enabled=rerank_enabled,
                    rerank_candidate_limit=int(
                        configuration.get("rerank_candidate_limit", 12)
                    ),
                    rerank_min_candidates=int(
                        configuration.get("rerank_min_candidates", 6)
                    ),
                    rerank_final_limit=int(
                        configuration.get("rerank_final_limit", 5)
                    ),
                    strategy=configuration.get(
                        "strategy", self._retrieval_unit_strategy
                    ),
                ),
                reranker=reranker,
                chunking_profile=self._chunking_profile,
            )
        answer_service = AnswerService(
            session=self._session,
            retrieval_service=retrieval_service,
            generation_provider=self._generation_provider,
        )
        answer_execution = await answer_service.answer_with_diagnostics(
            QuestionRequest(question=question.question),
            request_id=f"evaluation:{run_id}:{question.external_id}",
            workspace_id=workspace_id,
        )
        answer = answer_execution.response
        trace = await self._session.get(RetrievalTrace, answer.trace_id)
        retrieved_ids = trace.selected_passage_ids if trace is not None else []
        retrieved_document_ids = await self._document_ids(retrieved_ids)
        expected_passage_ids = {
            str(item["passage_id"])
            for item in question.expected_passages
            if item.get("passage_id") is not None
        }
        expected_document_ids = {
            str(item["document_id"])
            for item in question.expected_documents
            if item.get("document_id") is not None
        }
        checks = [
            {
                "passage_id": str(citation.passage_id),
                "document_name": citation.document_name,
                "structurally_valid": True,
                "matches_gold_evidence": (
                    str(citation.passage_id) in expected_passage_ids
                    or str(citation.document_id) in expected_document_ids
                ),
            }
            for citation in answer.citations
        ]
        actual_expectation = (
            "abstain"
            if answer.state == AnswerState.ABSTAINED
            else "partial"
            if answer.state == AnswerState.PARTIAL
            else "answer"
        )
        return {
            "retrieval_trace_id": answer.trace_id,
            "retrieved_ids": retrieved_ids,
            "retrieved_document_ids": list(
                dict.fromkeys(retrieved_document_ids.values())
            ),
            "generated_output": answer.model_dump(mode="json"),
            "answer_diagnostics": answer_execution.diagnostics.model_dump(
                mode="json"
            ),
            "citation_checks": checks,
            "actual_values": {"expectation": actual_expectation},
            "latency_ms": round((perf_counter() - started) * 1_000, 3),
        }

    async def _document_ids(self, passage_ids: list[str]) -> dict[str, str]:
        if not passage_ids:
            return {}
        rows = (
            await self._session.execute(
                select(Passage.id, Document.id)
                .join(
                    DocumentVersion,
                    DocumentVersion.id == Passage.document_version_id,
                )
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(Passage.id.in_([UUID(item) for item in passage_ids]))
            )
        ).all()
        return {str(passage_id): str(document_id) for passage_id, document_id in rows}
