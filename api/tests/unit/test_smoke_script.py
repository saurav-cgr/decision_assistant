import os
from pathlib import Path
import subprocess


SMOKE_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "smoke.sh"
PROJECT_ROOT = SMOKE_SCRIPT.parents[1]


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
