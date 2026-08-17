from hashlib import sha256
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.answering.diagnostics import AnswerOutcomeReason
from decision_assistant.answering.schemas import (
    Citation,
    DecisionFieldEvidence,
    EvidencePassage,
    QuestionRequest,
    SourceCitation,
)
from decision_assistant.answering.service import AnswerService
from decision_assistant.providers.fakes import FakeGenerationProvider
from decision_assistant.retrieval.schemas import (
    RetrievalResult,
    RetrievalSearchResponse,
)
from decision_assistant.retrieval.service import HybridRetrievalService

PASSAGE_ID = UUID("11111111-1111-1111-1111-111111111111")
TRACE_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
CONTENT = (
    "Proposal: Start an employee-only authentication beta on July 15, 2026. "
    "Priya Nair is the decision owner."
)


class StubRetrievalService:
    def __init__(self, *, include_result: bool = True) -> None:
        self.include_result = include_result

    async def search(self, *args: object, **kwargs: object) -> RetrievalSearchResponse:
        results = (
            [
                RetrievalResult(
                    passage_id=PASSAGE_ID,
                    content=CONTENT,
                    locator={"kind": "lines", "start": 1, "end": 1},
                    fused_score=1.0,
                    source_ranks={"semantic": 1},
                )
            ]
            if self.include_result
            else []
        )
        return RetrievalSearchResponse(trace_id=TRACE_ID, results=results)


class DiagnosticAnswerService(AnswerService):
    def __init__(
        self,
        provider: FakeGenerationProvider,
        *,
        include_evidence: bool = True,
    ) -> None:
        self.include_evidence = include_evidence
        super().__init__(
            session=cast(AsyncSession, None),
            retrieval_service=cast(
                HybridRetrievalService,
                StubRetrievalService(include_result=include_evidence),
            ),
            generation_provider=provider,
        )

    async def _load_active_passages(
        self,
        passage_ids: list[UUID],
    ) -> list[EvidencePassage]:
        if not self.include_evidence or not passage_ids:
            return []
        return [
            EvidencePassage(
                passage_id=PASSAGE_ID,
                content=CONTENT,
                content_hash=sha256(CONTENT.encode()).hexdigest(),
                active_version=True,
            )
        ]

    async def _load_decision_fields(
        self,
        passage_ids: list[UUID],
    ) -> list[DecisionFieldEvidence]:
        return []

    async def _source_citations(
        self,
        citations: list[Citation],
    ) -> list[SourceCitation]:
        return [
            SourceCitation(
                **citation.model_dump(),
                document_id=DOCUMENT_ID,
                document_name="architecture-sync.md",
                locator={"kind": "lines", "start": 1, "end": 1},
            )
            for citation in citations
        ]


def invalid_citation_candidate() -> dict[str, object]:
    return {
        "answer": "The beta would start July 15, 2026.",
        "claims": [
            {
                "text": "The beta would start July 15, 2026.",
                "central": True,
                "passage_ids": [str(PASSAGE_ID)],
            }
        ],
        "citations": [
            {
                "passage_id": str(PASSAGE_ID),
                "quote": "The beta starts on July 15.",
            }
        ],
        "conflicts": [],
        "unsupported_facets": [],
        "confidence": "high",
    }


def supported_candidate(*, central: bool = True) -> dict[str, object]:
    return {
        "answer": "The beta would start July 15, 2026.",
        "claims": [
            {
                "text": "The beta would start July 15, 2026.",
                "central": central,
                "passage_ids": [str(PASSAGE_ID)],
                "explicit_dates": ["July 15, 2026"],
            }
        ],
        "citations": [
            {
                "passage_id": str(PASSAGE_ID),
                "quote": "July 15, 2026",
            }
        ],
        "conflicts": [],
        "unsupported_facets": [],
        "confidence": "high",
    }


def abstention_candidate() -> dict[str, object]:
    return {
        "answer": "Insufficient evidence to answer that question.",
        "claims": [],
        "citations": [],
        "conflicts": [],
        "unsupported_facets": ["exact public launch date"],
        "confidence": "none",
    }


@pytest.mark.asyncio
async def test_diagnostics_preserve_candidate_and_verifier_failure() -> None:
    provider = FakeGenerationProvider(
        [invalid_citation_candidate(), invalid_citation_candidate()]
    )
    service = DiagnosticAnswerService(provider)

    execution = await service.answer_with_diagnostics(
        QuestionRequest(question="When would the beta start?"),
        request_id="diagnostic-failure",
    )

    assert execution.response.state == "abstained"
    assert execution.response.claims == []
    assert execution.diagnostics.outcome_reason == (
        AnswerOutcomeReason.CITATION_MATERIALIZATION_FAILED
    )
    assert execution.diagnostics.raw_candidate is not None
    assert execution.diagnostics.raw_candidate.claims[0].central is True
    assert execution.diagnostics.materialized_answer is not None
    assert execution.diagnostics.materialized_answer.citations == []
    assert execution.diagnostics.dropped_citations[0].reason == "quote_not_exact"
    assert execution.diagnostics.verifier_errors[0].code == (
        "claim_citation_invalid"
    )
    assert execution.diagnostics.repair_attempted is True
    assert execution.diagnostics.repair_candidate is not None
    assert execution.diagnostics.repair_dropped_citations[0].reason == (
        "quote_not_exact"
    )
    assert execution.diagnostics.repair_verifier_errors[0].code == (
        "claim_citation_invalid"
    )
    assert execution.diagnostics.generation_attempt_count == 2
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_invalid_citation_is_repaired_once() -> None:
    provider = FakeGenerationProvider(
        [invalid_citation_candidate(), supported_candidate()]
    )
    service = DiagnosticAnswerService(provider)

    execution = await service.answer_with_diagnostics(
        QuestionRequest(question="When would the beta start?"),
        request_id="repair-invalid-citation",
    )

    assert execution.response.state == "answered"
    assert execution.response.citations[0].quote == "July 15, 2026"
    assert execution.diagnostics.outcome_reason == AnswerOutcomeReason.ANSWERED
    assert execution.diagnostics.dropped_citations[0].reason == "quote_not_exact"
    assert execution.diagnostics.repair_dropped_citations == []
    assert execution.diagnostics.repair_verifier_errors == []
    assert execution.diagnostics.generation_attempt_count == 2
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_missing_central_claim_is_repaired_once() -> None:
    provider = FakeGenerationProvider(
        [supported_candidate(central=False), supported_candidate()]
    )
    service = DiagnosticAnswerService(provider)

    execution = await service.answer_with_diagnostics(
        QuestionRequest(question="When would the beta start?"),
        request_id="repair-central-claim",
    )

    assert execution.response.state == "answered"
    assert execution.diagnostics.raw_candidate is not None
    assert execution.diagnostics.raw_candidate.claims[0].central is False
    assert execution.diagnostics.repair_candidate is not None
    assert execution.diagnostics.repair_candidate.claims[0].central is True
    assert execution.diagnostics.generation_attempt_count == 2


@pytest.mark.asyncio
async def test_false_model_abstention_can_be_repaired_to_answer() -> None:
    provider = FakeGenerationProvider(
        [abstention_candidate(), supported_candidate()]
    )
    service = DiagnosticAnswerService(provider)

    execution = await service.answer_with_diagnostics(
        QuestionRequest(
            question=(
                "What authentication change was proposed, when would it start, "
                "and who owned it?"
            )
        ),
        request_id="repair-false-abstention",
    )

    assert execution.response.state == "answered"
    assert execution.diagnostics.outcome_reason == AnswerOutcomeReason.ANSWERED
    assert execution.diagnostics.raw_candidate is not None
    assert execution.diagnostics.raw_candidate.unsupported_facets
    assert execution.diagnostics.repair_candidate is not None
    assert execution.diagnostics.repair_candidate.claims[0].central is True
    assert execution.diagnostics.generation_attempt_count == 2
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_diagnostics_distinguish_model_abstention() -> None:
    provider = FakeGenerationProvider(
        [abstention_candidate(), abstention_candidate()]
    )
    service = DiagnosticAnswerService(provider)

    execution = await service.answer_with_diagnostics(
        QuestionRequest(question="What is the exact public launch date?"),
        request_id="diagnostic-model-abstention",
    )

    assert execution.response.state == "abstained"
    assert execution.diagnostics.outcome_reason == AnswerOutcomeReason.MODEL_ABSTAINED
    assert execution.diagnostics.verifier_errors == []
    assert execution.diagnostics.repair_attempted is True
    assert execution.diagnostics.repair_verifier_errors == []
    assert execution.diagnostics.generation_attempt_count == 2
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_diagnostics_identify_no_evidence_without_generation() -> None:
    provider = FakeGenerationProvider()
    service = DiagnosticAnswerService(provider, include_evidence=False)

    execution = await service.answer_with_diagnostics(
        QuestionRequest(question="Who owns authentication?"),
        request_id="diagnostic-no-evidence",
    )

    assert execution.response.state == "abstained"
    assert execution.diagnostics.outcome_reason == AnswerOutcomeReason.NO_EVIDENCE
    assert execution.diagnostics.raw_candidate is None
    assert execution.diagnostics.generation_attempt_count == 0
    assert provider.requests == []
