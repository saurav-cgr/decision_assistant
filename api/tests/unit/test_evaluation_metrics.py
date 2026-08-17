from importlib import import_module
from decimal import Decimal

import pytest


def test_top_five_hit_rate_counts_only_first_five_results() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")
    retrieved = [
        ["x1", "x2", "x3", "x4", "gold-a", "x6"],
        ["x1", "x2", "x3", "x4", "x5", "gold-b"],
    ]
    expected = [{"gold-a"}, {"gold-b"}]

    assert metrics.top_five_hit_rate(retrieved, expected) == 0.5
    assert metrics.top_five_hit_rate([], []) == 0.0


def test_mrr_counts_miss_as_zero() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")

    assert metrics.mean_reciprocal_rank(
        [["gold", "x"], ["x", "y"]],
        [{"gold"}, {"gold"}],
    ) == 0.5
    assert metrics.mean_reciprocal_rank([], []) == 0.0


def test_citation_rates_separate_structure_from_claim_support() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")
    checks = [
        {"structurally_valid": True, "supports_claim": True},
        {"structurally_valid": True, "supports_claim": False},
        {"structurally_valid": False, "supports_claim": True},
    ]

    rates = metrics.citation_rates(checks)

    assert rates.structural_validity == pytest.approx(2 / 3)
    assert rates.correctness == pytest.approx(1 / 3)


def test_gold_citation_coverage_is_question_level() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")

    assert metrics.gold_citation_coverage(
        [
            [
                {"matches_gold_evidence": False},
                {"matches_gold_evidence": True},
            ],
            [{"matches_gold_evidence": False}],
        ]
    ) == 0.5
    assert metrics.gold_citation_coverage([]) == 0.0


def test_answer_abstention_accuracy_is_question_level() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")

    assert metrics.answer_abstention_accuracy(
        ["answer", "abstain", "answer", "abstain"],
        ["answer", "answer", "answer", "abstain"],
    ) == 0.75


def test_partial_abstention_accuracy_is_scored_per_facet() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")
    expected = [
        {"what": "answer", "why": "abstain"},
        {"who": "answer", "when": "answer"},
    ]
    actual = [
        {"what": "answer", "why": "answer"},
        {"who": "answer", "when": "answer"},
    ]

    assert metrics.facet_abstention_accuracy(expected, actual) == 0.75
    assert metrics.facet_abstention_accuracy([], []) == 0.0


def test_latency_summary_reports_median_and_nearest_rank_p95() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")

    summary = metrics.latency_summary([100.0, 200.0, 300.0, 400.0])

    assert summary.median_ms == 250.0
    assert summary.p95_ms == 400.0
    assert metrics.latency_summary([]).median_ms == 0.0
    assert metrics.latency_summary([]).p95_ms == 0.0


def test_claim_support_rate_aggregates_atomic_claims() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")

    assert metrics.claim_support_rate([True, False, True]) == pytest.approx(2 / 3)
    assert metrics.claim_support_rate([]) == 0.0


def test_decision_metrics_track_winner_provenance_and_stability() -> None:
    metrics = import_module("decision_assistant.evaluation.metrics")

    assert metrics.decision_rank_accuracy(["a", "b"], ["a", "x"]) == 0.5
    assert metrics.decision_rank_accuracy([], []) == 0.0
    assert metrics.mean_evidence_backed_weight(
        [Decimal("0.4"), Decimal("1")]
    ) == pytest.approx(0.7)
    assert metrics.mean_evidence_backed_weight([]) == 0.0
    assert metrics.sensitivity_stability_accuracy([True, False], [True, True]) == 0.5
    assert metrics.sensitivity_stability_accuracy([], []) == 0.0
