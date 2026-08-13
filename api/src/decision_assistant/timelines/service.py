from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.errors import ApplicationError
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    DecisionRelation,
    Document,
    DocumentVersion,
    Passage,
)
from decision_assistant.timelines.schemas import (
    TimelineEntry,
    TimelineEvidence,
    TimelineRelationship,
    TimelineResponse,
)


class TimelineApiError(ApplicationError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class TimelineSortCandidate:
    decision_id: UUID
    effective_date: date | None
    document_date: date | None
    created_at: datetime

    @property
    def sort_date(self) -> date | None:
        return self.effective_date or self.document_date

    @property
    def date_is_fallback(self) -> bool:
        return self.effective_date is None and self.document_date is not None


def order_timeline_candidates(
    candidates: list[TimelineSortCandidate],
) -> list[TimelineSortCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.sort_date is None,
            candidate.sort_date or date.max,
            candidate.created_at,
            str(candidate.decision_id),
        ),
    )


@dataclass(frozen=True, slots=True)
class StoredEvidence:
    evidence: DecisionEvidence
    passage: Passage
    document_id: UUID


class TimelineService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_timeline(
        self,
        topic: str,
        *,
        candidate_decision_ids: list[UUID] | None = None,
        workspace_id: UUID | None = None,
    ) -> TimelineResponse:
        normalized_topic = self._normalize_topic(topic)
        if not normalized_topic:
            raise TimelineApiError("invalid_topic", "Topic cannot be empty", 422)

        statement = (
            select(Decision, DocumentVersion)
            .join(
                DocumentVersion,
                DocumentVersion.id == Decision.document_version_id,
            )
            .where(
                Decision.retired.is_(False),
                Decision.review_state == "supported",
            )
        )
        if workspace_id is not None:
            statement = statement.join(
                Document, Document.id == DocumentVersion.document_id
            ).where(Document.workspace_id == workspace_id)
        rows = (await self._session.execute(statement)).all()
        stored = {decision.id: (decision, version) for decision, version in rows}
        candidate_ids = set(candidate_decision_ids or [])
        selected_ids = {
            decision.id
            for decision, _ in rows
            if (
                decision.topic is not None
                and self._normalize_topic(decision.topic) == normalized_topic
            )
            or decision.id in candidate_ids
        }

        relations = list(await self._session.scalars(select(DecisionRelation)))
        selected_ids = self._expand_relations(selected_ids, stored, relations)
        evidence_by_decision = await self._load_active_evidence(selected_ids)
        selected_ids = {
            decision_id
            for decision_id in selected_ids
            if evidence_by_decision.get(decision_id)
        }
        relevant_relations = [
            relation
            for relation in relations
            if relation.source_decision_id in selected_ids
            and relation.target_decision_id in selected_ids
        ]

        sort_candidates = [
            TimelineSortCandidate(
                decision_id=decision_id,
                effective_date=stored[decision_id][0].effective_date,
                document_date=stored[decision_id][1].document_date,
                created_at=stored[decision_id][0].created_at,
            )
            for decision_id in selected_ids
        ]
        ordered = order_timeline_candidates(sort_candidates)
        superseded_ids = {
            relation.target_decision_id
            for relation in relevant_relations
            if relation.relation_type == "supersedes"
            and relation.authority == "user_confirmed"
        }
        relationships_by_source: dict[UUID, list[DecisionRelation]] = {}
        for relation in relevant_relations:
            relationships_by_source.setdefault(
                relation.source_decision_id,
                [],
            ).append(relation)

        entries: list[TimelineEntry] = []
        for candidate in ordered:
            decision, _ = stored[candidate.decision_id]
            entries.append(
                TimelineEntry(
                    decision_id=decision.id,
                    statement=decision.statement,
                    effective_date=decision.effective_date,
                    display_date=candidate.sort_date,
                    date_is_fallback=candidate.date_is_fallback,
                    original_status=decision.status,
                    display_status=(
                        "superseded"
                        if decision.id in superseded_ids
                        else decision.status
                    ),
                    owner=decision.owner,
                    project=decision.project,
                    topic=decision.topic,
                    provenance=decision.provenance,
                    evidence=[
                        self._evidence_response(item)
                        for item in evidence_by_decision[decision.id]
                    ],
                    relationships=[
                        self._relationship_response(relation)
                        for relation in sorted(
                            relationships_by_source.get(decision.id, []),
                            key=lambda item: (
                                item.relation_type,
                                str(item.target_decision_id),
                            ),
                        )
                    ],
                )
            )
        return TimelineResponse(topic=normalized_topic, entries=entries)

    async def _load_active_evidence(
        self,
        decision_ids: set[UUID],
    ) -> dict[UUID, list[StoredEvidence]]:
        if not decision_ids:
            return {}
        rows = (
            await self._session.execute(
                select(DecisionEvidence, Passage, DocumentVersion, Document)
                .join(Passage, Passage.id == DecisionEvidence.passage_id)
                .join(
                    DocumentVersion,
                    DocumentVersion.id == Passage.document_version_id,
                )
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    DecisionEvidence.decision_id.in_(decision_ids),
                    DecisionEvidence.support_state == "supported",
                    DocumentVersion.state == "active",
                    Document.active_version_id == DocumentVersion.id,
                )
                .order_by(
                    DecisionEvidence.is_primary.desc(),
                    DecisionEvidence.created_at,
                )
            )
        ).all()
        by_decision: dict[UUID, list[StoredEvidence]] = {}
        for evidence, passage, _, document in rows:
            by_decision.setdefault(evidence.decision_id, []).append(
                StoredEvidence(
                    evidence=evidence,
                    passage=passage,
                    document_id=document.id,
                )
            )
        return by_decision

    @staticmethod
    def _expand_relations(
        selected_ids: set[UUID],
        stored: dict[UUID, tuple[Decision, DocumentVersion]],
        relations: list[DecisionRelation],
    ) -> set[UUID]:
        expanded = set(selected_ids)
        changed = True
        while changed:
            changed = False
            for relation in relations:
                endpoints = {
                    relation.source_decision_id,
                    relation.target_decision_id,
                }
                if expanded & endpoints:
                    available = endpoints & stored.keys()
                    if not available <= expanded:
                        expanded.update(available)
                        changed = True
        return expanded

    @staticmethod
    def _evidence_response(item: StoredEvidence) -> TimelineEvidence:
        evidence = item.evidence
        passage = item.passage
        return TimelineEvidence(
            passage_id=passage.id,
            document_id=item.document_id,
            document_version_id=passage.document_version_id,
            quote=passage.content[evidence.start_offset : evidence.end_offset],
            start_offset=evidence.start_offset,
            end_offset=evidence.end_offset,
            content_hash=evidence.content_hash,
            locator=passage.locator,
        )

    @staticmethod
    def _relationship_response(
        relation: DecisionRelation,
    ) -> TimelineRelationship:
        label = (
            "possible_revision"
            if relation.authority == "model_inferred"
            else relation.relation_type
        )
        return TimelineRelationship(
            source_decision_id=relation.source_decision_id,
            target_decision_id=relation.target_decision_id,
            relation_type=relation.relation_type,
            label=label,
            authority=relation.authority,
            confidence=relation.confidence,
            rationale=relation.rationale,
        )

    @staticmethod
    def _normalize_topic(topic: str) -> str:
        return " ".join(topic.split()).casefold()
