from fastapi.testclient import TestClient

from decision_assistant.main import create_app


def decision_request() -> dict[str, object]:
    return {
        "title": "Choose deployment",
        "options": [
            {"id": "managed", "label": "Managed"},
            {"id": "self_hosted", "label": "Self-hosted"},
        ],
        "criteria": [
            {
                "id": "cost",
                "label": "Cost",
                "direction": "cost",
                "weight": "0.4",
                "scale": "numeric",
            },
            {
                "id": "quality",
                "label": "Quality",
                "direction": "benefit",
                "weight": "0.6",
                "scale": "ordinal",
            },
        ],
        "scores": [
            {
                "option_id": "managed",
                "criterion_id": "cost",
                "value": "100",
                "provenance": "user_provided",
            },
            {
                "option_id": "managed",
                "criterion_id": "quality",
                "value": "8",
                "provenance": "user_provided",
            },
            {
                "option_id": "self_hosted",
                "criterion_id": "cost",
                "value": "40",
                "provenance": "user_provided",
            },
            {
                "option_id": "self_hosted",
                "criterion_id": "quality",
                "value": "6",
                "provenance": "user_provided",
            },
        ],
    }


def test_decision_analysis_api_returns_verified_deterministic_result() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/decision-analyses", json=decision_request()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["algorithm_version"] == "weighted-sum-v1"
    assert [item["option_id"] for item in body["ranked_options"]] == [
        "managed",
        "self_hosted",
    ]
    assert body["ranked_options"][0]["total_score"] == "0.6"
    assert body["verification"] == {
        "valid": True,
        "errors": [],
        "warnings": ["user-provided scores affect the ranking"],
    }


def test_decision_analysis_api_rejects_incomplete_score_matrix() -> None:
    request = decision_request()
    request["scores"] = request["scores"][:-1]  # type: ignore[index]

    response = TestClient(create_app()).post("/api/v1/decision-analyses", json=request)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["message"] == "Request validation failed"
