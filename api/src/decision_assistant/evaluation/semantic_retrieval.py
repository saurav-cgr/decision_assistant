from time import perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.ingestion.profiles import CURRENT_CHUNKING_PROFILE
from decision_assistant.ingestion.retrieval_units import RetrievalUnitStrategy
from decision_assistant.providers.base import EmbeddingProvider, EmbeddingPurpose
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.retrieval.repository import RetrievalRepository
from decision_assistant.retrieval.schemas import (
    RetrievalResult,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from decision_assistant.workspace.embedding_profile import (
    require_current_corpus_profiles,
)
from decision_assistant.workspace.service import WorkspaceService


class SemanticRetrievalService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider,
        top_k: int,
        chunking_profile: dict[str, object] | None = None,
        retrieval_unit_strategy: RetrievalUnitStrategy = "passage_hybrid",
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._top_k = top_k
        self._repository = RetrievalRepository(session)
        self._chunking_profile = (
            chunking_profile if chunking_profile is not None else CURRENT_CHUNKING_PROFILE
        )
        self._retrieval_unit_strategy = retrieval_unit_strategy

    async def search(
        self,
        request: RetrievalSearchRequest,
        *,
        request_id: str,
        workspace_id: UUID | None = None,
    ) -> RetrievalSearchResponse:
        started = perf_counter()
        if workspace_id is None:
            workspace_id = (
                await WorkspaceService(self._session).get_or_create_active()
            ).id
        normalized = request.question.lower()
        await require_current_corpus_profiles(
            self._session,
            self._embedding_provider.profile,
            self._chunking_profile,
            workspace_id=workspace_id,
        )
        embedding = (
            await self._embedding_provider.embed(
                [normalized],
                purpose=EmbeddingPurpose.QUERY,
            )
        )[0]
        ranked = await self._repository.semantic_search(
            embedding,
            request.filters,
            embedding_profile=self._embedding_provider.profile.as_dict(),
            limit=self._top_k,
            workspace_id=workspace_id,
            retrieval_unit_kind=(
                "passage"
                if self._retrieval_unit_strategy == "passage_hybrid"
                else "sentence"
            ),
        )
        elapsed_ms = round((perf_counter() - started) * 1_000, 3)
        trace = RetrievalTrace(
            workspace_id=workspace_id,
            request_id=request_id,
            normalized_question=normalized,
            filters=request.filters.model_dump(mode="json", exclude_none=True),
            semantic_candidates=[
                {
                    "passage_id": str(item.passage.id),
                    "rank": rank,
                    "raw_score": item.raw_score,
                }
                for rank, item in enumerate(ranked, start=1)
            ],
            keyword_candidates=[],
            decision_candidates=[],
            fused_results=[
                {
                    "passage_id": str(item.passage.id),
                    "score": item.raw_score,
                    "source_ranks": {"semantic": rank},
                }
                for rank, item in enumerate(ranked, start=1)
            ],
            selected_passage_ids=[str(item.passage.id) for item in ranked],
            timings={"semantic_ms": elapsed_ms, "total_ms": elapsed_ms},
            configuration={"strategy": "semantic", "top_k": self._top_k},
        )
        self._session.add(trace)
        await self._session.flush()
        return RetrievalSearchResponse(
            trace_id=trace.id,
            results=[
                RetrievalResult(
                    passage_id=item.passage.id,
                    content=item.passage.content,
                    locator=item.passage.locator,
                    fused_score=item.raw_score,
                    source_ranks={"semantic": rank},
                )
                for rank, item in enumerate(ranked, start=1)
            ],
        )
