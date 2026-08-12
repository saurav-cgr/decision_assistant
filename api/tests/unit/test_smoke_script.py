import importlib.util
import os
from pathlib import Path
import subprocess

import pytest


SMOKE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "smoke.sh"
PROJECT_ROOT = SMOKE_SCRIPT.parents[1]
SMOKE_RUNNER = PROJECT_ROOT / "scripts" / "smoke.py"


def _load_smoke_runner():
    spec = importlib.util.spec_from_file_location("smoke_runner", SMOKE_RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gemini_preflight_uses_compose_resolved_api_environment() -> None:
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert '[[ -z "${GEMINI_API_KEY:-}" ]]' not in script
    assert 'os.environ.get("GEMINI_API_KEY", "").strip()' in script
    assert 'run --rm --no-deps api python -c' in script


def test_gemini_preflight_failure_never_prints_secret_value() -> None:
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")

    assert 'echo "$GEMINI_API_KEY"' not in script
    assert "GEMINI_API_KEY is required for Gemini mode" in script


def test_fake_override_blanks_key_and_removes_all_host_ports() -> None:
    fake_override = (PROJECT_ROOT / "compose.smoke.yaml").read_text(
        encoding="utf-8"
    )
    isolation_override = (PROJECT_ROOT / "compose.isolated.yaml").read_text(
        encoding="utf-8"
    )

    assert 'GEMINI_API_KEY: ""' in fake_override
    assert set(("db", "api", "web")) <= {
        line.removesuffix(":").strip()
        for line in isolation_override.splitlines()
        if line.startswith("  ") and not line.startswith("    ")
    }
    assert isolation_override.count("ports: !reset []") == 3


def test_preflight_failure_uses_unique_project_and_always_cleans_up(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_DOCKER_LOG\"\n"
        "if [[ \"$*\" == *'run --rm --no-deps api python -c'* ]]; then\n"
        "  exit 2\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    secret = "must-not-appear"
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(log_path),
        "SMOKE_PROVIDER_MODE": "gemini",
        "COMPOSE_PROJECT_NAME": "normal-development-stack",
        "GEMINI_API_KEY": secret,
    }

    completed = subprocess.run(
        ["bash", str(SMOKE_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert secret not in completed.stdout + completed.stderr
    commands = log_path.read_text(encoding="utf-8").splitlines()
    assert commands
    assert all("-p decision-assistant-smoke-" in command for command in commands)
    assert all("normal-development-stack" not in command for command in commands)
    assert all("-f compose.isolated.yaml" in command for command in commands)
    assert "run --rm --no-deps api python -c" in commands[0]
    assert "down --volumes --remove-orphans" in commands[-1]
    assert "--rmi local" in commands[-1]


def test_wait_for_active_document_fails_immediately_on_terminal_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_smoke_runner()
    document_id = "document-1"
    requested_urls: list[str] = []

    def request_json(url: str, **_kwargs: object) -> dict[str, object]:
        requested_urls.append(url)
        if url.endswith(f"/documents/{document_id}"):
            return {"active_version": None, "passages": []}
        if url.endswith("/documents"):
            return {
                "items": [
                    {
                        "id": document_id,
                        "status": "failed",
                        "error": {
                            "code": "provider_response_invalid",
                            "message": "must not appear",
                        },
                    }
                ]
            }
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(smoke, "_request_json", request_json)
    monkeypatch.setattr(
        smoke.time,
        "sleep",
        lambda _seconds: pytest.fail("terminal failure must not poll again"),
    )

    with pytest.raises(smoke.SmokeFailure) as caught:
        smoke._wait_for_active_document(document_id)

    assert str(caught.value) == (
        "Document document-1 ingestion failed: provider_response_invalid"
    )
    assert "must not appear" not in str(caught.value)
    assert requested_urls == [
        f"{smoke.API_V1}/documents/{document_id}",
        f"{smoke.API_V1}/documents",
    ]
