from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.documents.router import get_document_service
from decision_assistant.main import create_app
from decision_assistant.workspace.embedding_profile import CorpusResetRequired


class StubDocumentService:
    async def list_documents(self) -> dict[str, list[object]]:
        return {"items": []}


def test_health_reports_ready() -> None:
    app = create_app(Settings(gemini_api_key=None))
    session = AsyncMock()
    app.dependency_overrides[get_session] = _session_override(session)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    session.execute.assert_awaited_once()


def _session_override(session: AsyncMock):
    async def override() -> AsyncIterator[AsyncMock]:
        yield session

    return override


def test_ready_reports_sanitized_degraded_state_when_gemini_key_is_missing() -> None:
    app = create_app(Settings(gemini_api_key=None))
    session = AsyncMock()
    app.dependency_overrides[get_session] = _session_override(session)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "service_not_ready"
    assert response.json()["message"] == "Service is not ready"
    assert response.json()["details"] is None
    assert "key" not in response.text.casefold()
    session.scalars.assert_not_awaited()


def test_ready_checks_configuration_and_migration_without_creating_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(gemini_api_key="configured-not-validated"))
    session = AsyncMock()
    app.dependency_overrides[get_session] = _session_override(session)
    app.state.provider_bundle_factory = lambda: pytest.fail(
        "readiness must not create or call a remote provider"
    )
    profile_seen = None

    async def current_profile(_session: object, profile: object, chunking: object) -> None:
        nonlocal profile_seen
        profile_seen = profile

    monkeypatch.setattr(
        "decision_assistant.main.require_current_corpus_profiles",
        current_profile,
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert profile_seen is not None
    assert profile_seen.provider == "gemini"


def test_ready_is_degraded_while_corpus_reset_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(gemini_api_key="configured-not-validated"))
    session = AsyncMock()
    app.dependency_overrides[get_session] = _session_override(session)

    async def pending(*_: object) -> None:
        raise CorpusResetRequired()

    monkeypatch.setattr(
        "decision_assistant.main.require_current_corpus_profiles",
        pending,
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "service_not_ready"
    assert response.json()["details"] is None


def test_ready_accepts_selected_ollama_configuration_without_gemini_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            generation_provider="ollama",
            embedding_provider="ollama",
            gemini_api_key=None,
        )
    )
    session = AsyncMock()
    app.dependency_overrides[get_session] = _session_override(session)

    async def current_profile(*_: object) -> None:
        return None

    monkeypatch.setattr(
        "decision_assistant.main.require_current_corpus_profiles",
        current_profile,
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 200


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

    assert "/api/v1/workspaces/{workspace_id}/documents" in paths
    assert "/documents" not in paths
    assert "/health" in paths
    assert "/api/v1/health" not in paths
    assert all(
        path in {"/health", "/ready"} or path.startswith("/api/v1/")
        for path in paths
    )
    assert client.get("/documents").status_code == 404
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.asyncio
async def test_lifespan_closes_provider_factory_when_application_errors() -> None:
    app = create_app(
        Settings(
            auth_jwt_secret="test-signing-secret-for-lifespan-tests",
            auth_bootstrap_username="bootstrap-user",
            auth_bootstrap_password="bootstrap-password",
        )
    )
    close_calls = 0

    class Factory:
        async def aclose(self) -> None:
            nonlocal close_calls
            close_calls += 1

    app.state.provider_bundle_factory = Factory()

    with pytest.raises(RuntimeError, match="lifespan failure"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("lifespan failure")

    assert close_calls == 1
