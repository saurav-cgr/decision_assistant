"""Centralized corpus chunking-profile contract.

The current schema generation stores a single non-null chunking profile on
every ``DocumentVersion``. The corrected ``structural-token-v2`` serializer can
change chunk boundaries and passage content, so every named preset reports the
same algorithm version; a stored ``structural-token-v1`` corpus or a different
preset is treated as incompatible. There is no legacy profile and no in-place
migration path: changing chunking or embedding contracts requires an explicit
database reset and complete reingestion while the project remains under
development policy.

Service boundaries (ingestion, readiness, retrieval, evaluation) resolve a
profile once from application settings so they all compare against the same
mapping instead of importing a bare constant.
"""

from __future__ import annotations

# Named presets over the ``structural-token-v2`` algorithm. Every preset shares
# the same tokenizer encoding; only the token budget changes between presets.
CHUNKING_PROFILE_PRESETS: dict[str, dict[str, object]] = {
    "baseline": {
        "algorithm": "structural-token-v2",
        "encoding": "cl100k_base",
        "target_tokens": 450,
        "max_tokens": 600,
        "overlap_tokens": 60,
    },
    "compact": {
        "algorithm": "structural-token-v2",
        "encoding": "cl100k_base",
        "target_tokens": 250,
        "max_tokens": 350,
        "overlap_tokens": 40,
    },
    "expanded": {
        "algorithm": "structural-token-v2",
        "encoding": "cl100k_base",
        "target_tokens": 700,
        "max_tokens": 900,
        "overlap_tokens": 80,
    },
}

DEFAULT_CHUNKING_PROFILE_PRESET = "baseline"

# Canonical default mapping: the resolved ``baseline`` preset. New service
# boundaries resolve a profile from application settings; this constant remains
# the default when no explicit profile is injected (e.g. offline tests).
CURRENT_CHUNKING_PROFILE: dict[str, object] = CHUNKING_PROFILE_PRESETS[
    DEFAULT_CHUNKING_PROFILE_PRESET
]


def resolve_chunking_profile(preset: str) -> dict[str, object]:
    """Return the complete chunking profile for a named preset.

    Unknown presets fail fast with ``ValueError`` so a misconfiguration is
    caught at startup rather than silently producing an incompatible corpus.
    """
    if preset not in CHUNKING_PROFILE_PRESETS:
        raise ValueError(
            f"Unknown chunking profile preset {preset!r}; "
            f"expected one of {sorted(CHUNKING_PROFILE_PRESETS)}"
        )
    return CHUNKING_PROFILE_PRESETS[preset]
