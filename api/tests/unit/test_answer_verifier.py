from hashlib import sha256
from uuid import UUID, uuid4

from decision_assistant.answering.schemas import (
    AnswerClaim,
    AnswerState,
    Citation,
    ConfidenceCategory,
    DecisionFieldEvidence,
    EvidenceConflict,
    EvidencePassage,
    GeneratedAnswer,
)
from decision_assistant.answering.service import build_evidence_pack
from decision_assistant.answering.verifier import AnswerVerifier


PASSAGE_ID = UUID("11111111-1111-1111-1111-111111111111")
SECOND_PASSAGE_ID = UUID("22222222-2222-2222-2222-222222222222")
CONTENT = "Authentication was postponed because the billing launch had priority."
QUOTE = "Authentication was postponed"
QUOTE_START = CONTENT.index(QUOTE)
QUOTE_END = QUOTE_START + len(QUOTE)
CONTENT_HASH = sha256(CONTENT.encode()).hexdigest()


def evidence_passage(
    passage_id: UUID = PASSAGE_ID,
    *,
    content: str = CONTENT,
) -> EvidencePassage:
    return EvidencePassage(
        passage_id=passage_id,
        content=content,
        content_hash=sha256(content.encode()).hexdigest(),
        active_version=True,
    )


def citation(
    passage_id: UUID = PASSAGE_ID,
    *,
    quote: str = QUOTE,
    start_offset: int = QUOTE_START,
    end_offset: int = QUOTE_END,
    content_hash: str = CONTENT_HASH,
) -> Citation:
    return Citation(
        passage_id=passage_id,
        quote=quote,
        start_offset=start_offset,
        end_offset=end_offset,
        content_hash=content_hash,
    )


def generated_answer(
    *,
    claims: list[AnswerClaim] | None = None,
    citations: list[Citation] | None = None,
    conflicts: list[EvidenceConflict] | None = None,
    unsupported_facets: list[str] | None = None,
) -> GeneratedAnswer:
    return GeneratedAnswer(
        answer="Authentication was postponed.",
        claims=claims
        if claims is not None
        else [
            AnswerClaim(
                text="Authentication was postponed.",
                central=True,
                passage_ids=[PASSAGE_ID],
            )
        ],
        citations=citations if citations is not None else [citation()],
        conflicts=conflicts or [],
        unsupported_facets=unsupported_facets or [],
        confidence=ConfidenceCategory.HIGH,
    )


def test_verifier_accepts_exact_quote_with_matching_offsets_and_hash() -> None:
    result = AnswerVerifier().verify(
        generated_answer(),
        {PASSAGE_ID: evidence_passage()},
    )

    assert result.valid is True
    assert result.state == AnswerState.ANSWERED
    assert result.errors == []


def test_verifier_rejects_unknown_passage() -> None:
    unknown_id = uuid4()
    answer = generated_answer(
        claims=[
            AnswerClaim(
                text="Authentication was postponed.",
                central=True,
                passage_ids=[unknown_id],
            )
        ],
        citations=[citation(unknown_id)],
    )

    result = AnswerVerifier().verify(answer, {PASSAGE_ID: evidence_passage()})

    assert result.valid is False
    assert result.errors[0].code == "citation_passage_not_found"


def test_verifier_rejects_stale_citation_hash() -> None:
    answer = generated_answer(citations=[citation(content_hash="0" * 64)])

    result = AnswerVerifier().verify(answer, {PASSAGE_ID: evidence_passage()})

    assert result.valid is False
    assert result.errors[0].code == "citation_hash_mismatch"


def test_verifier_rejects_wrong_offsets() -> None:
    answer = generated_answer(
        citations=[
            citation(
                start_offset=QUOTE_START + 1,
                end_offset=QUOTE_END + 1,
            )
        ]
    )

    result = AnswerVerifier().verify(answer, {PASSAGE_ID: evidence_passage()})

    assert result.valid is False
    assert result.errors[0].code == "citation_offsets_mismatch"


def test_verifier_rejects_uncited_central_claim() -> None:
    answer = generated_answer(
        claims=[
            AnswerClaim(
                text="Authentication was postponed.",
                central=True,
                passage_ids=[],
            )
        ],
        citations=[],
    )

    result = AnswerVerifier().verify(answer, {PASSAGE_ID: evidence_passage()})

    assert result.valid is False
    assert result.errors[0].code == "central_claim_uncited"


def test_evidence_pack_excludes_unsupported_corrected_field() -> None:
    fields = [
        DecisionFieldEvidence(
            field_name="owner",
            value="Maya",
            passage_id=PASSAGE_ID,
            provenance="user_corrected",
            support_state="unsupported",
        ),
        DecisionFieldEvidence(
            field_name="status",
            value="proposed",
            passage_id=PASSAGE_ID,
            provenance="extracted",
            support_state="supported",
        ),
    ]

    pack = build_evidence_pack([evidence_passage()], fields)

    assert [field.field_name for field in pack.decision_fields] == ["status"]


def test_verifier_returns_conflict_with_both_citations() -> None:
    second_content = "Authentication was approved by Ravi."
    second_quote = "Authentication was approved"
    second_hash = sha256(second_content.encode()).hexdigest()
    answer = generated_answer(
        citations=[
            citation(),
            citation(
                SECOND_PASSAGE_ID,
                quote=second_quote,
                start_offset=0,
                end_offset=len(second_quote),
                content_hash=second_hash,
            ),
        ],
        conflicts=[
            EvidenceConflict(
                facet="status",
                passage_ids=[PASSAGE_ID, SECOND_PASSAGE_ID],
            )
        ],
    )

    result = AnswerVerifier().verify(
        answer,
        {
            PASSAGE_ID: evidence_passage(),
            SECOND_PASSAGE_ID: evidence_passage(
                SECOND_PASSAGE_ID,
                content=second_content,
            ),
        },
    )

    assert result.valid is True
    assert result.state == AnswerState.CONFLICTED
    assert result.conflicts[0].passage_ids == [PASSAGE_ID, SECOND_PASSAGE_ID]


def test_verifier_accepts_app_detected_conflict_citing_evidence_pack_passage() -> (
    None
):
    second_content = "Priya Nair owns authentication readiness."
    answer = generated_answer(
        citations=[citation()],
        conflicts=[
            EvidenceConflict(
                facet="owner",
                passage_ids=[PASSAGE_ID, SECOND_PASSAGE_ID],
            )
        ],
    )

    result = AnswerVerifier().verify(
        answer,
        {
            PASSAGE_ID: evidence_passage(),
            SECOND_PASSAGE_ID: evidence_passage(
                SECOND_PASSAGE_ID,
                content=second_content,
            ),
        },
    )

    # An app-detected conflict may cite a second evidence-pack passage that the
    # model did not quote. That is competing evidence to display, not a failure.
    assert result.valid is True
    assert result.state == AnswerState.CONFLICTED
    assert result.conflicts[0].passage_ids == [PASSAGE_ID, SECOND_PASSAGE_ID]


def test_verifier_returns_partial_when_only_some_facets_are_supported() -> None:
    result = AnswerVerifier().verify(
        generated_answer(unsupported_facets=["who changed it later"]),
        {PASSAGE_ID: evidence_passage()},
    )

    assert result.valid is True
    assert result.state == AnswerState.PARTIAL
    assert result.unsupported_facets == ["who changed it later"]


def test_verifier_fully_abstains_without_a_supported_central_claim() -> None:
    answer = generated_answer(
        claims=[],
        citations=[],
        unsupported_facets=["why authentication was postponed"],
    )

    result = AnswerVerifier().verify(answer, {PASSAGE_ID: evidence_passage()})

    assert result.valid is True
    assert result.state == AnswerState.ABSTAINED
