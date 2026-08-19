import asyncio
from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.errors import ApplicationError
from decision_assistant.models import DocumentVersion, Passage, RetrievalTrace
from decision_assistant.providers.base import EmbeddingProvider, EmbeddingPurpose
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.retrieval.repository import RankedPassage, RetrievalRepository
from decision_assistant.retrieval.reranking import (
    RerankCandidate,
    RerankingProvider,
    resolve_reranked_order,
)
from decision_assistant.retrieval.rrf import reciprocal_rank_fusion
from decision_assistant.retrieval.schemas import (
    RetrievalResult,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    RetrievalTraceResponse,
)
from decision_assistant.workspace.embedding_profile import (
    require_current_corpus_profiles,
)
from decision_assistant.workspace.service import WorkspaceService


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    semantic_limit: int = 20
    keyword_limit: int = 20
    decision_limit: int = 20
    rrf_k: int = 60
    top_k: int = 5
    rerank_enabled: bool = False
    rerank_candidate_limit: int = 12
    rerank_min_candidates: int = 6
    rerank_final_limit: int = 5

    def __post_init__(self) -> None:
        if self.semantic_limit < 1 or self.keyword_limit < 1 or self.decision_limit < 1:
            raise ValueError("retrieval limits must be positive")
        if self.rrf_k < 1 or self.top_k < 1:
            raise ValueError("rrf_k and top_k must be positive")
        if self.rerank_candidate_limit < 1 or self.rerank_min_candidates < 1:
            raise ValueError("rerank limits must be positive")
        if self.rerank_final_limit < 1:
            raise ValueError("rerank_final_limit must be positive")
        if self.rerank_final_limit > self.rerank_candidate_limit:
            raise ValueError("rerank_final_limit must not exceed rerank_candidate_limit")
        if self.rerank_min_candidates > self.rerank_candidate_limit:
            raise ValueError("rerank_min_candidates must not exceed rerank_candidate_limit")
    top_k: int = 5
    rerank_enabled: bool = False
    rerank_candidate_limit: int = 12
    rerank_min_candidates: int = 6
    rerank_final_limit: int = 5

    def __post_init__(self) -> None:
        if self.semantic_limit < 1 or self.keyword_limit < 1 or self.decision_limit < 1:
            raise ValueError("retrieval limits must be positive")
        if self.rrf_k < 1 or self.top_k < 1:
            raise ValueError("rrf_k and top_k must be positive")
        if self.rerank_candidate_limit < 1 or self.rerank_min_candidates < 1:
            raise ValueError("rerank limits must be positive")
        if self.rerank_final_limit < 1:
            raise ValueError("rerank_final_limit must be positive")
        if self.rerank_final_limit > self.rerank_candidate_limit:
            raise ValueError("rerank_final_limit must not exceed rerank_candidate_limit")
        if self.rerank_min_candidates > self.rerank_candidate_limit:
            raise ValueError("rerank_min_candidates must not exceed rerank_candidate_limit")

    def as_dict(self) -> dict[str, object]:
        return {
            "semantic_limit": self.semantic_limit,
            "keyword_limit": self.keyword_limit,
            "decision_limit": self.decision_limit,
            "rrf_k": self.rrf_k,
            "top_k": self.top_k,
            "rerank_enabled": self.rerank_enabled,
            "rerank_candidate_limit": self.rerank_candidate_limit,
            "rerank_min_candidates": self.rerank_min_candidates,
            "rerank_final_limit": self.rerank_final_limit,
        }


class RetrievalNotFound(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="not_found",
            message="Retrieval trace not found",
            status_code=404,
            retryable=False,
        )


class HybridRetrievalService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        config: RetrievalConfig | None = None,
        reranker: RerankingProvider | None = None,
        chunking_profile: dict[str, object] | None = None,
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._config = config or RetrievalConfig()
        self._reranker = reranker
        self._repository = RetrievalRepository(session)
        self._chunking_profile = (
            chunking_profile if chunking_profile is not None else CURRENT_CHUNKING_PROFILE
        )

    async def search(
        self,
        request: RetrievalSearchRequest,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> RetrievalSearchResponse:
        total_started = perf_counter()
        if workspace_id is None:
            workspace_id = (
                await WorkspaceService(self._session).get_or_create_active()
            ).id
        normalized_question = request.question.lower()
        await require_current_corpus_profiles(
            self._session,
            self._embedding_provider.profile,
            self._chunking_profile,
            workspace_id=workspace_id,
        )
        embedding = (
            await self._embedding_provider.embed(
                [normalized_question],
                purpose=EmbeddingPurpose.QUERY,
            )
        )[0]

        semantic_started = perf_counter()
        semantic = await self._repository.semantic_search(
            embedding,
            request.filters,
            embedding_profile=self._embedding_provider.profile.as_dict(),
            limit=self._config.semantic_limit,
            workspace_id=workspace_id,
        )
        semantic_ms = _elapsed_ms(semantic_started)

        keyword_started = perf_counter()
        keyword = await self._repository.keyword_search(
            normalized_question,
            request.filters,
            limit=self._config.keyword_limit,
            workspace_id=workspace_id,
        )
        keyword_ms = _elapsed_ms(keyword_started)

        decision_started = perf_counter()
        decision = await self._repository.decision_search(
            normalized_question,
            request.filters,
            limit=self._config.decision_limit,
            workspace_id=workspace_id,
        )
        decision_ms = _elapsed_ms(decision_started)

        fusion_started = perf_counter()
        candidates = {
            "semantic": semantic,
            "keyword": keyword,
            "decision": decision,
        }
        fused = reciprocal_rank_fusion(
            {
                source: [item.passage.id for item in ranked]
                for source, ranked in candidates.items()
            },
            k=self._config.rrf_k,
        )
        fusion_ms = _elapsed_ms(fusion_started)

        passage_by_id: dict[UUID, Passage] = {
            item.passage.id: item.passage
            for ranked in candidates.values()
            for item in ranked
        }
        fused_by_id = {item.id: item for item in fused}
        selected_ids, rerank_block, rerank_ms = await self._select_with_rerank(
            fused=fused,
            question=request.question,
            passage_by_id=passage_by_id,
        )
        selected_passage_metadata = await self._selected_passage_metadata(
            selected_ids, passage_by_id
        )

        filters = request.filters.model_dump(mode="json", exclude_none=True)
        timings = {
            "semantic_ms": semantic_ms,
            "keyword_ms": keyword_ms,
            "decision_ms": decision_ms,
            "fusion_ms": fusion_ms,
            "rerank_ms": rerank_ms,
            "total_ms": _elapsed_ms(total_started),
        }
        trace = RetrievalTrace(
            workspace_id=workspace_id,
            request_id=request_id,
            normalized_question=normalized_question,
            filters=filters,
            semantic_candidates=_candidate_trace(semantic),
            keyword_candidates=_candidate_trace(keyword),
            decision_candidates=_candidate_trace(decision),
            fused_results=[
                {
                    "passage_id": str(item.id),
                    "score": item.score,
                    "source_ranks": item.source_ranks,
                }
                for item in fused
            ],
            selected_passage_ids=[str(item) for item in selected_ids],
            selected_passage_metadata=selected_passage_metadata,
            rerank=rerank_block,
            timings=timings,
            configuration=self._config.as_dict(),
        )
        self._session.add(trace)
        await self._session.flush()

        return RetrievalSearchResponse(
            trace_id=trace.id,
            results=[
                RetrievalResult(
                    passage_id=item,
                    content=passage_by_id[item].content,
                    locator=passage_by_id[item].locator,
                    fused_score=fused_by_id[item].score,
                    source_ranks=fused_by_id[item].source_ranks,
                )
                for item in selected_ids
            ],
        )

    async def _select_with_rerank(
        self,
        *,
        fused: list[RankedPassage],
        question: str,
        passage_by_id: dict[UUID, Passage],
    ) -> tuple[list[UUID], dict[str, object] | None, float]:
        rerank_block: dict[str, object] | None = None
        rerank_ms = 0.0
        if (
            self._reranker is not None
            and self._config.rerank_enabled
            and len(fused) >= self._config.rerank_min_candidates
        ):
            started = perf_counter()
            candidate_scope = fused[: self._config.rerank_candidate_limit]
            candidate_ids = [item.id for item in candidate_scope]
            candidates = [
                RerankCandidate(
                    passage_id=passage_id,
                    content=passage_by_id[passage_id].content,
                )
                for passage_id in candidate_ids
            ]
            status = "completed"
            fallback_reason: str | None = None
            ordered: list[UUID] | None = None
            try:
                model_ids = await self._reranker.rerank(question, candidates)
                ordered = resolve_reranked_order(model_ids, candidate_ids)
                if ordered is None:
                    status = "invalid_output"
                    fallback_reason = "invalid_output"
            except asyncio.CancelledError:
                raise
            except Exception:
                status = "provider_error"
                fallback_reason = "provider_error"
            rerank_ms = _elapsed_ms(started)
            rerank_block = {
                "status": status,
                "input_passage_ids": [str(item) for item in candidate_ids],
                "output_passage_ids": [str(item) for item in (ordered or candidate_ids)],
                "profile": self._reranker.profile,
                "fallback_reason": fallback_reason,
            }
            if ordered is not None:
                selected = ordered[: self._config.rerank_final_limit]
            else:
                selected = candidate_ids[: self._config.rerank_final_limit]
            return selected, rerank_block, rerank_ms
        return (
            [item.id for item in fused[: self._config.top_k]],
            rerank_block,
            rerank_ms,
        )

    async def _selected_passage_metadata(
        self,
        selected_ids: list[UUID],
        passage_by_id: dict[UUID, Passage],
    ) -> list[dict[str, object]]:
        if not selected_ids:
            return []
        version_ids = {
            passage_by_id[passage_id].document_version_id for passage_id in selected_ids
        }
        versions = {
            version.id: version
            for version in await self._session.scalars(
                select(DocumentVersion).where(DocumentVersion.id.in_(version_ids))
            )
        }
        return [
            {
                "passage_id": str(passage_id),
                "document_version_id": str(
                    passage_by_id[passage_id].document_version_id
                ),
                "chunking_profile": versions[
                    passage_by_id[passage_id].document_version_id
                ].chunking_profile,
                "source_kind": _source_kind(passage_by_id[passage_id].locator),
            }
            for passage_id in selected_ids
        ]

    async def get_trace(
        self,
        trace_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> RetrievalTraceResponse:
        trace = await self._session.get(RetrievalTrace, trace_id)
        if trace is None or (
            workspace_id is not None and trace.workspace_id != workspace_id
        ):
            raise RetrievalNotFound()
        return RetrievalTraceResponse(
            id=trace.id,
            request_id=trace.request_id,
            normalized_question=trace.normalized_question,
            filters=trace.filters,
            semantic_candidates=trace.semantic_candidates,
            keyword_candidates=trace.keyword_candidates,
            decision_candidates=trace.decision_candidates,
            fused_results=trace.fused_results,
            selected_passage_ids=trace.selected_passage_ids,
            selected_passage_metadata=trace.selected_passage_metadata,
            rerank=trace.rerank,
            timings=trace.timings,
            configuration=trace.configuration,
            created_at=trace.created_at,
        )


def _source_kind(locator: dict[str, object]) -> str:
    kind = locator.get("kind")
    if kind == "slack_message" or (
        kind == "message_range" and locator.get("source") == "slack"
    ):
        return "slack"
    if kind == "teams_message" or (
        kind == "message_range" and locator.get("source") == "teams"
    ):
        return "teams"
    if kind == "pdf_page":
        return "pdf"
    if kind == "docx_paragraphs":
        return "docx"
    return "text"


def _candidate_trace(candidates: list[RankedPassage]) -> list[dict[str, object]]:
    return [
        {
            "passage_id": str(candidate.passage.id),
            "rank": rank,
            "raw_score": candidate.raw_score,
        }
        for rank, candidate in enumerate(candidates, start=1)
    ]


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)
