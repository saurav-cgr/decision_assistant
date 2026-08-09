from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Text, cast, exists, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    Document,
    DocumentVersion,
    Passage,
)
from decision_assistant.retrieval.schemas import RetrievalFilters


@dataclass(frozen=True, slots=True)
class RankedPassage:
    passage: Passage
    raw_score: float


class RetrievalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def semantic_search(
        self,
        embedding: list[float],
        filters: RetrievalFilters,
        *,
        limit: int,
    ) -> list[RankedPassage]:
        distance = Passage.embedding.cosine_distance(embedding).label("distance")
        statement = self._active_passages(select(Passage, distance), filters)
        rows = (
            await self._session.execute(statement.order_by(distance).limit(limit))
        ).all()
        return [
            RankedPassage(passage=passage, raw_score=1.0 - float(value))
            for passage, value in rows
        ]

    async def keyword_search(
        self,
        question: str,
        filters: RetrievalFilters,
        *,
        limit: int,
    ) -> list[RankedPassage]:
        query = func.websearch_to_tsquery(
            literal_column("'english'::regconfig"),
            question,
        )
        rank = func.ts_rank_cd(Passage.search_vector, query).label("rank")
        statement = self._active_passages(select(Passage, rank), filters).where(
            Passage.search_vector.op("@@")(query)
        )
        rows = (
            await self._session.execute(statement.order_by(rank.desc()).limit(limit))
        ).all()
        return [
            RankedPassage(passage=passage, raw_score=float(value))
            for passage, value in rows
        ]

    async def decision_search(
        self,
        question: str,
        filters: RetrievalFilters,
        *,
        limit: int,
    ) -> list[RankedPassage]:
        query = func.websearch_to_tsquery(
            literal_column("'english'::regconfig"),
            question,
        )
        searchable = func.concat_ws(
            " ",
            Decision.statement,
            Decision.owner,
            Decision.project,
            Decision.topic,
            cast(Decision.reasons, Text),
            cast(Decision.alternatives, Text),
        )
        vector = func.to_tsvector(
            literal_column("'english'::regconfig"),
            searchable,
        )
        rank = func.ts_rank_cd(vector, query).label("rank")
        statement = (
            select(Passage, rank)
            .join(DecisionEvidence, DecisionEvidence.passage_id == Passage.id)
            .join(Decision, Decision.id == DecisionEvidence.decision_id)
            .join(DocumentVersion, DocumentVersion.id == Passage.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                DocumentVersion.state == "active",
                Document.active_version_id == DocumentVersion.id,
                Decision.retired.is_(False),
                Decision.review_state == "supported",
                DecisionEvidence.support_state == "supported",
                vector.op("@@")(query),
                *self._filter_clauses(filters),
            )
            .order_by(rank.desc())
            .limit(limit * 2)
        )
        rows = (await self._session.execute(statement)).all()
        unique: list[RankedPassage] = []
        seen: set[UUID] = set()
        for passage, value in rows:
            if passage.id in seen:
                continue
            seen.add(passage.id)
            unique.append(RankedPassage(passage=passage, raw_score=float(value)))
            if len(unique) == limit:
                break
        return unique

    def _active_passages(
        self,
        statement: Select[Any],
        filters: RetrievalFilters,
    ) -> Select[Any]:
        return (
            statement.join(
                DocumentVersion,
                DocumentVersion.id == Passage.document_version_id,
            )
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                DocumentVersion.state == "active",
                Document.active_version_id == DocumentVersion.id,
                *self._filter_clauses(filters),
            )
        )

    def _filter_clauses(self, filters: RetrievalFilters) -> list[Any]:
        clauses: list[Any] = []
        if filters.person is not None:
            owner_evidence = exists(
                select(1)
                .select_from(DecisionEvidence)
                .join(Decision, Decision.id == DecisionEvidence.decision_id)
                .where(
                    DecisionEvidence.passage_id == Passage.id,
                    func.lower(Decision.owner) == filters.person.lower(),
                    Decision.retired.is_(False),
                    Decision.review_state == "supported",
                    DecisionEvidence.support_state == "supported",
                )
            )
            clauses.append(
                or_(
                    DocumentVersion.participants.contains([filters.person]),
                    owner_evidence,
                )
            )
        if filters.date_from is not None:
            clauses.append(DocumentVersion.document_date >= filters.date_from)
        if filters.date_to is not None:
            clauses.append(DocumentVersion.document_date <= filters.date_to)
        if filters.project is not None:
            clauses.append(func.lower(DocumentVersion.project) == filters.project.lower())
        if filters.document_type is not None:
            clauses.append(Document.media_type == filters.document_type)
        return clauses
