from enum import StrEnum
from uuid import UUID

from pydantic import Field

from decision_assistant.answering.schemas import (
    AnswerModel,
    AnswerState,
    Citation,
    EvidencePack,
    GeneratedAnswer,
    GeneratedAnswerCandidate,
    QuestionResponse,
    VerificationError,
    VerificationResult,
)


class AnswerOutcomeReason(StrEnum):
    ANSWERED = "answered"
    NO_EVIDENCE = "no_evidence"
    MODEL_ABSTAINED = "model_abstained"
    VERIFICATION_FAILED = "verification_failed"
    NO_SUPPORTED_CENTRAL_CLAIM = "no_supported_central_claim"
    CITATION_MATERIALIZATION_FAILED = "citation_materialization_failed"


class DroppedCitationReason(StrEnum):
    PASSAGE_NOT_FOUND = "passage_not_found"
    QUOTE_NOT_EXACT = "quote_not_exact"


class DroppedCitation(AnswerModel):
    passage_id: UUID
    quote: str
    reason: DroppedCitationReason


class MaterializationResult(AnswerModel):
    answer: GeneratedAnswer
    dropped_citations: list[DroppedCitation] = Field(default_factory=list)


class AnswerExecutionDiagnostics(AnswerModel):
    outcome_reason: AnswerOutcomeReason
    raw_candidate: GeneratedAnswerCandidate | None = None
    materialized_answer: GeneratedAnswer | None = None
    dropped_citations: list[DroppedCitation] = Field(default_factory=list)
    verifier_errors: list[VerificationError] = Field(default_factory=list)
    generation_attempt_count: int = Field(ge=0)


class AnswerExecution(AnswerModel):
    response: QuestionResponse
    diagnostics: AnswerExecutionDiagnostics


def materialize_generated_answer(
    candidate: GeneratedAnswerCandidate,
    evidence_pack: EvidencePack,
) -> MaterializationResult:
    passage_by_id = {
        passage.passage_id: passage for passage in evidence_pack.passages
    }
    citations = []
    dropped: list[DroppedCitation] = []
    for selected in candidate.citations:
        passage = passage_by_id.get(selected.passage_id)
        if passage is None:
            dropped.append(
                DroppedCitation(
                    passage_id=selected.passage_id,
                    quote=selected.quote,
                    reason=DroppedCitationReason.PASSAGE_NOT_FOUND,
                )
            )
            continue
        start_offset = passage.content.find(selected.quote)
        if start_offset < 0:
            dropped.append(
                DroppedCitation(
                    passage_id=selected.passage_id,
                    quote=selected.quote,
                    reason=DroppedCitationReason.QUOTE_NOT_EXACT,
                )
            )
            continue
        citations.append(
            Citation(
                passage_id=selected.passage_id,
                quote=selected.quote,
                start_offset=start_offset,
                end_offset=start_offset + len(selected.quote),
                content_hash=passage.content_hash,
            )
        )
    return MaterializationResult(
        answer=GeneratedAnswer(
            answer=candidate.answer,
            claims=candidate.claims,
            citations=citations,
            conflicts=candidate.conflicts,
            unsupported_facets=candidate.unsupported_facets,
            confidence=candidate.confidence,
        ),
        dropped_citations=dropped,
    )


def classify_outcome(
    candidate: GeneratedAnswerCandidate,
    verification: VerificationResult,
    dropped_citations: list[DroppedCitation],
) -> AnswerOutcomeReason:
    if not verification.valid:
        if dropped_citations:
            return AnswerOutcomeReason.CITATION_MATERIALIZATION_FAILED
        return AnswerOutcomeReason.VERIFICATION_FAILED
    if verification.state != AnswerState.ABSTAINED:
        return AnswerOutcomeReason.ANSWERED
    if (
        candidate.unsupported_facets
        and not candidate.claims
        and not candidate.citations
    ):
        return AnswerOutcomeReason.MODEL_ABSTAINED
    return AnswerOutcomeReason.NO_SUPPORTED_CENTRAL_CLAIM
