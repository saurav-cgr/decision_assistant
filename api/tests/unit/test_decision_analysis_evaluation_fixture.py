import json
from decimal import Decimal
from pathlib import Path

from decision_assistant.decision_analysis.schemas import DecisionAnalysisRequest
from decision_assistant.decision_analysis.scoring import calculate_decision
from decision_assistant.evaluation.metrics import (
    decision_rank_accuracy,
    mean_evidence_backed_weight,
    sensitivity_stability_accuracy,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = PROJECT_ROOT / "evaluation" / "decision_analysis_cases.json"


def test_decision_analysis_poc_fixture_has_expected_rank_stability_and_provenance() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert dataset["version"] == "decision-analysis-v1"

    results = [
        (case, calculate_decision(DecisionAnalysisRequest.model_validate(case["request"])))
        for case in dataset["cases"]
    ]

    assert decision_rank_accuracy(
        [case["expected_winner_option_id"] for case, _ in results],
        [response.ranked_options[0].option_id for _, response in results],
    ) == 1.0
    assert sensitivity_stability_accuracy(
        [case["expected_stable"] for case, _ in results],
        [response.sensitivity.stability == "stable" for _, response in results],
    ) == 1.0
    assert mean_evidence_backed_weight(
        [response.evidence_coverage.evidence_backed_weight for _, response in results]
    ) == float(Decimal("0.5"))
