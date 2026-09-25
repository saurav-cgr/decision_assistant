from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from decision_assistant.config import Settings
from decision_assistant.db import get_session
from decision_assistant.documents.router import get_document_service
from decision_assistant.main import create_app
from decision_assistant.version import get_app_version
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
    assert response.json() == {"status": "ok", "version": get_app_version()}
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
async def test_lifespan_closes_provider_factory_when_application_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This test enters the real lifespan context (not just TestClient's request
    # path), which runs every startup step up to `yield` for real, including a
    # real `pg_dump` subprocess since backup.py's create_pre_migration_backup
    # landed. Stub both the gate and the backup: the test only cares that
    # aclose() runs on error, not that a real backup happens (or that its
    # gate's real DB round-trip determines whether one would), and a real
    # pg_dump write to the host filesystem doesn't belong in a unit test's
    # side effects.
    monkeypatch.setattr(
        "decision_assistant.main.is_upgrade_pending",
        lambda settings: True,
    )
    monkeypatch.setattr(
        "decision_assistant.main.create_pre_migration_backup",
        lambda settings: None,
    )
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


@pytest.mark.asyncio
async def test_lifespan_skips_backup_and_still_upgrades_when_no_migration_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # V68: proves the `if is_upgrade_pending(...)` gate itself, not just the
    # gate function and the backup routine in isolation. Deleting the gate
    # or reordering backup after upgrade_to_head would leave this failing.
    import decision_assistant.main as main_module

    monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: False)

    backup_calls = 0

    def fake_backup(settings: object) -> None:
        nonlocal backup_calls
        backup_calls += 1

    monkeypatch.setattr(main_module, "create_pre_migration_backup", fake_backup)

    upgrade_calls = 0
    real_upgrade_to_head = main_module.upgrade_to_head

    def spied_upgrade_to_head() -> None:
        nonlocal upgrade_calls
        upgrade_calls += 1
        real_upgrade_to_head()

    monkeypatch.setattr(main_module, "upgrade_to_head", spied_upgrade_to_head)

    app = create_app(
        Settings(
            auth_jwt_secret="test-signing-secret-for-lifespan-tests",
            auth_bootstrap_username="bootstrap-user",
            auth_bootstrap_password="bootstrap-password",
        )
    )

    class Factory:
        async def aclose(self) -> None:
            return None

    app.state.provider_bundle_factory = Factory()

    async with app.router.lifespan_context(app):
        pass

    assert backup_calls == 0
    assert upgrade_calls == 1


@pytest.mark.asyncio
async def test_lifespan_blocks_migration_when_pre_migration_backup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # V68: a failed backup must block the migration, not be silently skipped.
    import decision_assistant.main as main_module

    monkeypatch.setattr(main_module, "is_upgrade_pending", lambda settings: True)

    def failing_backup(settings: object) -> None:
        raise RuntimeError("backup exploded")

    monkeypatch.setattr(main_module, "create_pre_migration_backup", failing_backup)

    upgrade_calls = 0

    def spied_upgrade_to_head() -> None:
        nonlocal upgrade_calls
        upgrade_calls += 1

    monkeypatch.setattr(main_module, "upgrade_to_head", spied_upgrade_to_head)

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

    with pytest.raises(RuntimeError, match="backup exploded"):
        async with app.router.lifespan_context(app):
            pass

    assert upgrade_calls == 0
    assert close_calls == 1
