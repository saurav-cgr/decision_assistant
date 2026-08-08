from fastapi.testclient import TestClient

from decision_assistant.documents.router import get_document_service
from decision_assistant.main import create_app


class StubDocumentService:
    async def list_documents(self) -> dict[str, list[object]]:
        return {"items": []}


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


def test_public_business_routes_use_v1_namespace() -> None:
    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: StubDocumentService()
    client = TestClient(app)
    paths = app.openapi()["paths"]

    assert "/api/v1/documents" in paths
    assert "/documents" not in paths
    assert "/health" in paths
    assert "/api/v1/health" not in paths
    assert all(path == "/health" or path.startswith("/api/v1/") for path in paths)
    assert client.get("/documents").status_code == 404
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
