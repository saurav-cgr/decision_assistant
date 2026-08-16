import pytest
from pydantic import ValidationError

from decision_assistant.evaluation.metrics import citation_rates
from decision_assistant.evaluation.schemas import ClaimJudgeOutput
from decision_assistant.evaluation.service import EvaluationService


def test_supporting_non_gold_citation_is_correct_but_not_gold_coverage() -> None:
    checks = EvaluationService._merge_citation_checks(
        {
            "claims": [
                {
                    "text": "The June proposal would start July 15.",
                    "passage_ids": ["later-revision"],
                }
            ]
        },
        [
            {
                "passage_id": "later-revision",
                "document_name": "03-auth-rollout.docx",
                "structurally_valid": True,
                "matches_gold_evidence": False,
            }
        ],
        {
            "citation_assessments": [
                {
                    "claim_index": 0,
                    "passage_id": "later-revision",
                    "supported": True,
                    "reason": "The revision identifies the June proposal and date.",
                }
            ]
        },
    )

    assert checks == [
        {
            "claim_index": 0,
            "claim": "The June proposal would start July 15.",
            "passage_id": "later-revision",
            "document_name": "03-auth-rollout.docx",
            "structurally_valid": True,
            "matches_gold_evidence": False,
            "supports_claim": True,
            "reason": "The revision identifies the June proposal and date.",
        }
    ]
    rates = citation_rates(checks)
    assert rates.structural_validity == 1.0
    assert rates.correctness == 1.0


def test_unlinked_citation_is_reported_as_unsupported() -> None:
    checks = EvaluationService._merge_citation_checks(
        {"claims": [{"text": "Supported directly.", "passage_ids": ["gold"]}]},
        [
            {
                "passage_id": "gold",
                "structurally_valid": True,
                "matches_gold_evidence": True,
            },
            {
                "passage_id": "unused",
                "structurally_valid": True,
                "matches_gold_evidence": False,
            },
        ],
        {
            "citation_assessments": [
                {
                    "claim_index": 0,
                    "passage_id": "gold",
                    "supported": True,
                    "reason": "Direct support.",
                }
            ]
        },
    )

    assert checks[0]["supports_claim"] is True
    assert checks[1]["claim_index"] is None
    assert checks[1]["supports_claim"] is False
    assert checks[1]["reason"] == "Citation is not linked to an answer claim."


def test_claim_judge_schema_requires_explicit_support_assessments() -> None:
    with pytest.raises(ValidationError):
        ClaimJudgeOutput.model_validate(
            {
                "claims": [
                    {
                        "text": "The model copied the generated claim.",
                        "passage_ids": ["gold"],
                    }
                ],
                "supported_claims": 1,
                "total_claims": 1,
            }
        )
