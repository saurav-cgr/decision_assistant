"""Unit tests for evaluation gold-reference passage resolution."""
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.evaluation.schemas import EvaluationDatasetQuestion
from decision_assistant.evaluation.service import EvaluationService


def _passage(locator: dict) -> SimpleNamespace:
    return SimpleNamespace(locator=locator)


def test_narrow_passage_matches_keeps_most_specific_on_boundary_overlap() -> None:
    # A gold locator on a chunk-overlap boundary is covered by two passages;
    # the smaller (more specific) range is the intended passage.
    matches = [
        _passage({"kind": "lines", "start": 1, "end": 31}),
        _passage({"kind": "lines", "start": 31, "end": 33}),
    ]
    narrowed = EvaluationService._narrow_passage_matches(matches)
    assert len(narrowed) == 1
    assert narrowed[0].locator == {"kind": "lines", "start": 31, "end": 33}


def test_narrow_passage_matches_keeps_singleton_unchanged() -> None:
    matches = [_passage({"kind": "lines", "start": 5, "end": 9})]
    assert EvaluationService._narrow_passage_matches(matches) == matches


def test_narrow_passage_matches_leaves_tied_spans_ambiguous() -> None:
    # Two distinct same-span passages covering the gold locator are genuine
    # ambiguity and must not be collapsed.
    matches = [
        _passage({"kind": "lines", "start": 2, "end": 10}),
        _passage({"kind": "lines", "start": 20, "end": 28}),
    ]
    assert len(EvaluationService._narrow_passage_matches(matches)) == 2


def test_narrow_passage_matches_pdf_pages_equally_specific() -> None:
    # pdf_page locators match on page identity; ties are left for the caller.
    matches = [
        _passage({"kind": "pdf_page", "page": 2}),
        _passage({"kind": "pdf_page", "page": 3}),
    ]
    assert len(EvaluationService._narrow_passage_matches(matches)) == 2


def test_locator_span_ignores_pdf_page() -> None:
    assert EvaluationService._locator_span({"kind": "pdf_page", "page": 4}) == 0
    assert EvaluationService._locator_span({"kind": "lines", "start": 31, "end": 33}) == 2


def test_gold_identifier_falls_back_to_stable_document_reference() -> None:
    expected = {
        "expected_passages": [{"document_id": "document-1"}],
        "expected_documents": [],
    }

    assert EvaluationService._expected_identifiers(expected) == {"document-1"}


@pytest.mark.asyncio
async def test_successful_result_copies_answer_diagnostics() -> None:
    service = EvaluationService(
        session=cast(AsyncSession, None),
        dataset_path=Path("unused.json"),
        executor=SimpleNamespace(),
        judge=SimpleNamespace(),
    )
    run = SimpleNamespace(id=uuid4(), judge_profile={})
    question = SimpleNamespace(
        id=uuid4(),
        question="Why was authentication postponed?",
        expected_answer_summary="Audit events were incomplete.",
        expected_documents=[],
        expected_passages=[],
    )
    snapshot = EvaluationDatasetQuestion(
        id="diagnostic-1",
        question=question.question,
        expectation="answer",
        facets={"reason": "answer"},
    )
    diagnostics = {
        "outcome_reason": "answered",
        "generation_attempt_count": 2,
    }

    result = await service._successful_result(
        run,
        question,
        snapshot,
        {
            "generated_output": {"claims": []},
            "actual_values": {"expectation": "answer"},
            "answer_diagnostics": diagnostics,
            "retrieved_ids": [],
            "citation_checks": [],
        },
    )

    assert result.answer_diagnostics == diagnostics
