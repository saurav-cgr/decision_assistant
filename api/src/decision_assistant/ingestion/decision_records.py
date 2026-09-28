"""Persistence of extracted decisions, their evidence and their relations.

Split out of `ingestion/service.py` (DB67): the service owns the document/version/job lifecycle,
this module owns the decision half of an ingestion — which passages are offered to the extractor,
how each extracted decision becomes a `Decision` with `DecisionEvidence`, and how a superseded
version's decisions are retired.
"""

from uuid import UUID

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.decisions.models import (
    Decision,
    DecisionEvidence,
    DecisionRelation,
)
from decision_assistant.decisions.schemas import ExtractionPassage
from decision_assistant.ingestion.models import Passage
from decision_assistant.ingestion.retrieval_units import (
    RetrievalUnitStrategy,
    canonical_decision_unit_kind,
)


async def persist_extracted_decisions(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    document_version_id: UUID,
    passages: list[Passage],
    decision_extractor: DecisionExtractor,
    retrieval_unit_strategy: RetrievalUnitStrategy,
) -> None:
    """Extract decisions from the decision-kind passages and store them with their evidence."""
    extracted_decisions = await decision_extractor.extract(
        [
            ExtractionPassage(
                passage_id=passage.id,
                content=passage.content,
                content_hash=passage.content_hash,
            )
            for passage in passages
            if passage.retrieval_unit_kind
            == canonical_decision_unit_kind(retrieval_unit_strategy)
        ]
    )
    passage_by_id = {passage.id: passage for passage in passages}
    decisions_with_relations: list[tuple[Decision, object | None]] = []
    for extracted in extracted_decisions:
        decision = Decision(
            workspace_id=workspace_id,
            document_version_id=document_version_id,
            statement=extracted.statement,
            effective_date=extracted.effective_date,
            owner=extracted.owner,
            status=extracted.status.value,
            reasons=extracted.reasons,
            alternatives=extracted.alternatives,
            project=extracted.project,
            topic=extracted.topic,
            extraction_confidence=extracted.extraction_confidence,
            provenance="extracted",
            review_state="supported",
            user_edited=False,
            retired=False,
        )
        session.add(decision)
        await session.flush()
        evidence = extracted.evidence
        passage = passage_by_id[evidence.passage_id]
        session.add(
            DecisionEvidence(
                decision_id=decision.id,
                passage_id=passage.id,
                field_name=None,
                start_offset=evidence.start_offset,
                end_offset=evidence.end_offset,
                support_state="supported",
                is_primary=True,
                content_hash=evidence.content_hash,
                quote=evidence.quote,
            )
        )
        decisions_with_relations.append((decision, extracted.relation))

    for decision, relation in decisions_with_relations:
        if relation is None:
            continue
        target = await session.get(Decision, relation.target_decision_id)
        if target is not None:
            session.add(
                DecisionRelation(
                    source_decision_id=decision.id,
                    target_decision_id=target.id,
                    relation_type=relation.relation_type.value,
                    authority="model_inferred",
                    confidence=relation.confidence.value,
                    rationale=relation.rationale,
                )
            )


async def retire_previous_decisions(session: AsyncSession, version_id: UUID) -> None:
    """Retire a superseded version's decisions, keeping user-corrected ones for review."""
    corrected = or_(
        Decision.user_edited.is_(True),
        Decision.provenance == "user_corrected",
    )
    await session.execute(
        update(Decision)
        .where(Decision.document_version_id == version_id, corrected)
        .values(review_state="needs_review")
    )
    await session.execute(
        update(Decision)
        .where(Decision.document_version_id == version_id, ~corrected)
        .values(retired=True)
    )
