from fastapi.testclient import TestClient

from decision_assistant.main import create_app


def test_health_reports_ready() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_uses_stable_error_shape() -> None:
    response = TestClient(create_app()).get("/missing")

    assert response.status_code == 404
    assert set(response.json()) >= {
        "code",
        "message",
        "request_id",
        "retryable",
    }
