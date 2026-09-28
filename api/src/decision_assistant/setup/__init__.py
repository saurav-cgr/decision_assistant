"""First-run setup (US5/FR-013): the secrets a fresh install must not share.

Why the file this writes lives on the host while the logic lives here: the api container receives
every setting as an explicit `environment:` entry in `compose.yaml`, and Compose substitutes those
from the host repo-root `.env`. A container cannot write that file — its filesystem is not the host's
— and the only mount that would let it is the repo root, which D4 forbids. So `scripts/setup.sh` owns
the file and this module owns the logic it applies: the same host-script plus in-container-module
split T037 uses for backup/restore. See loop debt DB58 for the full reasoning.
"""

from decision_assistant.setup.bootstrap import (
    ENV_KEYS,
    EnvUpdate,
    FirstRunSecrets,
    SetupError,
    apply_first_run_setup,
    env_is_configured,
    generate_first_run_secrets,
    generate_secret,
    parse_env_text,
    render_database_url,
    update_env_text,
)

__all__ = [
    "ENV_KEYS",
    "EnvUpdate",
    "FirstRunSecrets",
    "SetupError",
    "apply_first_run_setup",
    "env_is_configured",
    "generate_first_run_secrets",
    "generate_secret",
    "parse_env_text",
    "render_database_url",
    "update_env_text",
]
