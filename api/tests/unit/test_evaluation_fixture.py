import json
from pathlib import Path
from typing import Any

import pytest

from decision_assistant.evaluation.schemas import EvaluationDataset
from decision_assistant.ingestion.parsers import parse_document


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = PROJECT_ROOT / "evaluation" / "questions.json"
SAMPLE_ROOT = PROJECT_ROOT / "sample_data" / "atlas"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_sample_documents.py"
EXPECTED_SAMPLE_FILES = {
    "01-product-plan.md",
    "02-architecture-sync.md",
    "03-auth-rollout.docx",
    "04-q3-planning.pdf",
    "05-security-notes.txt",
}
VALID_STATUSES = {"active", "proposed", "rejected", "superseded"}


@pytest.fixture(scope="module")
def raw_dataset() -> dict[str, Any]:
    assert DATASET_PATH.is_file(), "evaluation/questions.json is missing"
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def questions(raw_dataset: dict[str, Any]) -> list[dict[str, Any]]:
    return raw_dataset["questions"]


def test_atlas_assets_exist_and_dataset_matches_runtime_schema(
    raw_dataset: dict[str, Any],
) -> None:
    assert BUILD_SCRIPT.is_file()
    assert EXPECTED_SAMPLE_FILES <= {
        path.name for path in SAMPLE_ROOT.iterdir() if path.is_file()
    }

    dataset = EvaluationDataset.model_validate(raw_dataset)

    assert dataset.version == "atlas-v3"
    assert len(dataset.questions) == 20


def test_question_ids_outcomes_conflicts_and_multi_part_coverage(
    questions: list[dict[str, Any]],
) -> None:
    ids = [question["id"] for question in questions]

    assert len(ids) == 20
    assert len(set(ids)) == 20
    assert sum(question["expectation"] == "abstain" for question in questions) >= 4
    assert sum("conflict" in question["tags"] for question in questions) >= 2
    assert sum(len(question["facets"]) >= 2 for question in questions) >= 2


def test_gold_questions_include_claims_sources_locators_and_statuses(
    questions: list[dict[str, Any]],
) -> None:
    observed_statuses: set[str] = set()
    for question in questions:
        assert "expected_claims" in question
        assert "expected_status" in question
        status = question["expected_status"]
        if status is not None:
            assert status in VALID_STATUSES
            observed_statuses.add(status)

        passages = question["expected_passages"]
        documents = question["expected_documents"]
        if question["expectation"] == "abstain":
            assert question["expected_claims"] == []
            assert passages == []
            assert documents == []
            continue

        assert question["expected_claims"]
        assert passages
        assert documents
        for expected in passages:
            assert set(expected) >= {"document", "quote", "locator"}
            assert expected["document"] in EXPECTED_SAMPLE_FILES
            assert expected["quote"].strip()
            assert expected["locator"].get("kind")

    assert {"active", "proposed", "rejected", "superseded"} <= observed_statuses


def test_every_gold_quote_and_locator_resolves_in_real_sample_files(
    questions: list[dict[str, Any]],
) -> None:
    parsed = {
        filename: parse_document(SAMPLE_ROOT / filename)
        for filename in EXPECTED_SAMPLE_FILES
    }

    for question in questions:
        for expected in question["expected_passages"]:
            matches = [
                block
                for block in parsed[expected["document"]].blocks
                if expected["quote"] in block.text
                and block.locator == expected["locator"]
            ]
            assert len(matches) == 1, (
                f'{question["id"]}: quote/locator did not uniquely resolve in '
                f'{expected["document"]}'
            )


def test_benchmark_covers_authentication_supersession_and_required_history(
    questions: list[dict[str, Any]],
) -> None:
    all_tags = {tag for question in questions for tag in question["tags"]}
    assert {
        "authentication",
        "june-proposal",
        "may-postponement",
        "priya-owner",
        "authorization-audit",
        "july-beta",
        "public-rollout",
        "conflict",
        "unrelated",
        "unsupported",
    } <= all_tags

    supersession = [
        question
        for question in questions
        if {"authentication", "supersession"} <= set(question["tags"])
    ]
    assert supersession
    assert any(question["expected_status"] == "superseded" for question in supersession)
    claims = " ".join(
        str(claim["text"])
        for question in supersession
        for claim in question["expected_claims"]
    ).casefold()
    assert "july" in claims
    assert "internal beta" in claims
    assert "public rollout" in claims
    assert "postponed" in claims
