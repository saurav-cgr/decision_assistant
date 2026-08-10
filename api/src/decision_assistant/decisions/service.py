from datetime import date
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.schemas import (
    DecisionChange,
    DecisionCorrectionRequest,
    DecisionDetail,
    DecisionEvidenceResponse,
    DecisionListResponse,
    DecisionRelationRequest,
    DecisionRelationResponse,
    DecisionRevisionResponse,
    DecisionSummary,
    EvidenceSelection,
)
from decision_assistant.errors import ApplicationError
from decision_assistant.models import (
    Decision,
    DecisionEvidence,
    DecisionRelation,
    DecisionRevision,
    Document,
    DocumentVersion,
    Passage,
)


class DecisionApiError(ApplicationError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            retryable=False,
        )


class DecisionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_decisions(
        self,
        *,
        status: str | None = None,
        owner: str | None = None,
        project: str | None = None,
        topic: str | None = None,
        review_state: str | None = None,
    ) -> DecisionListResponse:
        statement = select(Decision).where(Decision.retired.is_(False))
        filters = {
            "status": status,
            "owner": owner,
            "project": project,
            "topic": topic,
            "review_state": review_state,
        }
        for field_name, value in filters.items():
            if value is not None:
                statement = statement.where(getattr(Decision, field_name) == value)
        decisions = list(
            await self._session.scalars(
                statement.order_by(Decision.effective_date.desc().nullslast())
            )
        )
        return DecisionListResponse(
            items=[self._summary(decision) for decision in decisions]
        )

    async def get_decision(self, decision_id: UUID) -> DecisionDetail:
        decision = await self._require_decision(decision_id)
        evidence_rows = (
            await self._session.execute(
                select(DecisionEvidence, Passage)
                .join(Passage, Passage.id == DecisionEvidence.passage_id)
                .where(DecisionEvidence.decision_id == decision.id)
                .order_by(
                    DecisionEvidence.field_name.asc().nullsfirst(),
                    DecisionEvidence.is_primary.desc(),
                    DecisionEvidence.created_at,
                )
            )
        ).all()
        revisions = list(
            await self._session.scalars(
                select(DecisionRevision)
                .where(DecisionRevision.decision_id == decision.id)
                .order_by(DecisionRevision.created_at, DecisionRevision.id)
            )
        )
        relations = list(
            await self._session.scalars(
                select(DecisionRelation)
                .where(
                    or_(
                        DecisionRelation.source_decision_id == decision.id,
                        DecisionRelation.target_decision_id == decision.id,
                    )
                )
                .order_by(DecisionRelation.created_at, DecisionRelation.id)
            )
        )
        summary = self._summary(decision)
        return DecisionDetail(
            **summary.model_dump(),
            evidence=[
                DecisionEvidenceResponse(
                    passage_id=evidence.passage_id,
                    field_name=evidence.field_name,
                    quote=passage.content[
                        evidence.start_offset : evidence.end_offset
                    ],
                    start_offset=evidence.start_offset,
                    end_offset=evidence.end_offset,
                    content_hash=evidence.content_hash,
                    support_state=evidence.support_state,
                    is_primary=evidence.is_primary,
                )
                for evidence, passage in evidence_rows
            ],
            revisions=[self._revision_response(revision) for revision in revisions],
            relations=[self._relation_response(relation) for relation in relations],
        )

    async def correct_decision(
        self,
        decision_id: UUID,
        request: DecisionCorrectionRequest,
    ) -> DecisionDetail:
        decision = await self._require_decision(decision_id)
        previous_review_state = decision.review_state
        previous_revision_fields = set(
            await self._session.scalars(
                select(DecisionRevision.field_name).where(
                    DecisionRevision.decision_id == decision.id
                )
            )
        )
        current_states: dict[str, str] = {}

        for change in request.changes:
            evidence = await self._validate_evidence(change)
            old_value = getattr(decision, change.field_name)
            if old_value == change.value:
                continue

            setattr(decision, change.field_name, change.value)
            await self._session.execute(
                delete(DecisionEvidence).where(
                    DecisionEvidence.decision_id == decision.id,
                    DecisionEvidence.field_name == change.field_name,
                )
            )
            for index, (selection, passage) in enumerate(evidence):
                self._session.add(
                    DecisionEvidence(
                        decision_id=decision.id,
                        passage_id=passage.id,
                        field_name=change.field_name,
                        start_offset=selection.start_offset,
                        end_offset=selection.end_offset,
                        support_state="supported",
                        is_primary=index == 0,
                        content_hash=selection.content_hash,
                    )
                )
            self._session.add(
                DecisionRevision(
                    decision_id=decision.id,
                    field_name=change.field_name,
                    old_value=self._json_value(old_value),
                    new_value=self._json_value(change.value),
                    evidence_passage_ids=[passage.id for _, passage in evidence],
                    support_state=change.support_state,
                )
            )
            current_states[change.field_name] = change.support_state

        if current_states:
            decision.provenance = "user_corrected"
            decision.user_edited = True
            decision.review_state = await self._aggregate_review_state(
                decision.id,
                previous_review_state=previous_review_state,
                previous_revision_fields=previous_revision_fields,
                current_states=current_states,
            )
            await self._session.flush()
        return await self.get_decision(decision.id)

    async def create_relation(
        self,
        source_decision_id: UUID,
        request: DecisionRelationRequest,
    ) -> DecisionRelationResponse:
        await self._require_decision(source_decision_id)
        await self._require_decision(request.target_decision_id)
        if source_decision_id == request.target_decision_id:
            raise DecisionApiError(
                "invalid_relation",
                "A decision cannot relate to itself",
                422,
            )

        relation = await self._session.scalar(
            select(DecisionRelation).where(
                DecisionRelation.source_decision_id == source_decision_id,
                DecisionRelation.target_decision_id == request.target_decision_id,
                DecisionRelation.relation_type == request.relation_type.value,
            )
        )
        if relation is None:
            relation = DecisionRelation(
                source_decision_id=source_decision_id,
                target_decision_id=request.target_decision_id,
                relation_type=request.relation_type.value,
                authority="user_confirmed",
                confidence=None,
                rationale=request.rationale,
            )
            self._session.add(relation)
        else:
            relation.authority = "user_confirmed"
            relation.confidence = None
            relation.rationale = request.rationale
        await self._session.flush()
        return self._relation_response(relation)

    async def _validate_evidence(
        self,
        change: DecisionChange,
    ) -> list[tuple[EvidenceSelection, Passage]]:
        if change.support_state == "unsupported":
            return []

        validated: list[tuple[EvidenceSelection, Passage]] = []
        for selection in change.evidence:
            row = (
                await self._session.execute(
                    select(Passage, DocumentVersion, Document)
                    .join(
                        DocumentVersion,
                        DocumentVersion.id == Passage.document_version_id,
                    )
                    .join(Document, Document.id == DocumentVersion.document_id)
                    .where(Passage.id == selection.passage_id)
                )
            ).one_or_none()
            if row is None:
                raise DecisionApiError(
                    "evidence_not_found",
                    "Evidence passage not found",
                    409,
                )
            passage, version, document = row
            if (
                version.state != "active"
                or document.active_version_id != version.id
            ):
                raise DecisionApiError(
                    "inactive_evidence",
                    "Evidence must belong to an active document version",
                    409,
                )
            if selection.content_hash != passage.content_hash:
                raise DecisionApiError(
                    "stale_evidence",
                    "Evidence content hash no longer matches",
                    409,
                )
            if selection.end_offset > len(passage.content):
                raise DecisionApiError(
                    "invalid_evidence_span",
                    "Evidence offsets are outside the passage",
                    409,
                )
            validated.append((selection, passage))
        return validated

    async def _aggregate_review_state(
        self,
        decision_id: UUID,
        *,
        previous_review_state: str,
        previous_revision_fields: set[str],
        current_states: dict[str, str],
    ) -> str:
        revisions = list(
            await self._session.scalars(
                select(DecisionRevision)
                .where(DecisionRevision.decision_id == decision_id)
                .order_by(DecisionRevision.created_at, DecisionRevision.id)
            )
        )
        latest_states: dict[str, str] = {
            revision.field_name: revision.support_state for revision in revisions
        }
        latest_states.update(current_states)

        if "unsupported" in latest_states.values():
            return "unsupported"
        if "needs_review" in latest_states.values():
            return "needs_review"
        if previous_review_state == "needs_review" and not (
            previous_revision_fields <= current_states.keys()
        ):
            return "needs_review"
        return "supported"

    async def _require_decision(self, decision_id: UUID) -> Decision:
        decision = await self._session.get(Decision, decision_id)
        if decision is None:
            raise DecisionApiError(
                "decision_not_found",
                "Decision not found",
                404,
            )
        return decision

    @staticmethod
    def _summary(decision: Decision) -> DecisionSummary:
        return DecisionSummary(
            id=decision.id,
            document_version_id=decision.document_version_id,
            statement=decision.statement,
            effective_date=decision.effective_date,
            owner=decision.owner,
            status=decision.status,
            reasons=decision.reasons,
            alternatives=decision.alternatives,
            project=decision.project,
            topic=decision.topic,
            extraction_confidence=decision.extraction_confidence,
            provenance=decision.provenance,
            review_state=decision.review_state,
            user_edited=decision.user_edited,
            retired=decision.retired,
        )

    @staticmethod
    def _revision_response(revision: DecisionRevision) -> DecisionRevisionResponse:
        return DecisionRevisionResponse(
            id=revision.id,
            field_name=revision.field_name,
            old_value=revision.old_value,
            new_value=revision.new_value,
            evidence_passage_ids=revision.evidence_passage_ids,
            support_state=revision.support_state,
        )

    @staticmethod
    def _relation_response(relation: DecisionRelation) -> DecisionRelationResponse:
        return DecisionRelationResponse(
            id=relation.id,
            source_decision_id=relation.source_decision_id,
            target_decision_id=relation.target_decision_id,
            relation_type=relation.relation_type,
            authority=relation.authority,
            confidence=relation.confidence,
            rationale=relation.rationale,
        )

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, date):
            return value.isoformat()
        return jsonable_encoder(value)
