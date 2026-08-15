from dataclasses import dataclass
from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.errors import ApplicationError
from decision_assistant.models import Passage, RetrievalTrace
from decision_assistant.providers.base import EmbeddingProvider, EmbeddingPurpose
from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.retrieval.repository import RankedPassage, RetrievalRepository
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

    def as_dict(self) -> dict[str, int]:
        return {
            "semantic_limit": self.semantic_limit,
            "keyword_limit": self.keyword_limit,
            "decision_limit": self.decision_limit,
            "rrf_k": self.rrf_k,
            "top_k": self.top_k,
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
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._config = config or RetrievalConfig()
        self._repository = RetrievalRepository(session)

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
            CURRENT_CHUNKING_PROFILE,
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
        selected = fused[: self._config.top_k]
        fusion_ms = _elapsed_ms(fusion_started)

        passage_by_id: dict[UUID, Passage] = {
            item.passage.id: item.passage
            for ranked in candidates.values()
            for item in ranked
        }
        filters = request.filters.model_dump(mode="json", exclude_none=True)
        timings = {
            "semantic_ms": semantic_ms,
            "keyword_ms": keyword_ms,
            "decision_ms": decision_ms,
            "fusion_ms": fusion_ms,
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
            selected_passage_ids=[str(item.id) for item in selected],
            timings=timings,
            configuration=self._config.as_dict(),
        )
        self._session.add(trace)
        await self._session.flush()

        return RetrievalSearchResponse(
            trace_id=trace.id,
            results=[
                RetrievalResult(
                    passage_id=item.id,
                    content=passage_by_id[item.id].content,
                    locator=passage_by_id[item.id].locator,
                    fused_score=item.score,
                    source_ranks=item.source_ranks,
                )
                for item in selected
            ],
        )

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
            timings=trace.timings,
            configuration=trace.configuration,
            created_at=trace.created_at,
        )


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
