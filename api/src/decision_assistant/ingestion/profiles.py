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

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

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
RETRIEVAL_UNIT_STRATEGIES = frozenset(
    {"passage_hybrid", "sentence_expanded", "parent_child_merged"}
)


def _resolved_core_version() -> str:
    """Return the ``docling-core`` distribution version actually installed.

    ``docling==2.130.0`` pins the distribution that exposes the public API but
    leaves its own parsing core floating, so two builds of the same commit can
    install different ``docling-core`` releases (observed: 2.98.1 -> 2.99.0).
    Parse output depends on that core — block mapping, reading order, locator
    boxes — so it belongs in the corpus contract: when it changes, stored
    passages are no longer comparable and readiness must demand a reset rather
    than silently serving re-chunked content.
    """
    try:
        return _distribution_version("docling-core")
    except PackageNotFoundError:  # pragma: no cover - docling is a hard dependency
        return "unavailable"


PDF_PARSER_PROFILE: dict[str, str] = {
    "name": "docling",
    "version": "2.130.0",
    "core_version": _resolved_core_version(),
    "ocr": "tesseract-eng",
    "layout": "docling-layout-v1",
}


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


def resolve_corpus_profile(
    preset: str,
    retrieval_unit_strategy: str,
) -> dict[str, object]:
    """Return the complete incompatible corpus representation contract."""
    if retrieval_unit_strategy not in RETRIEVAL_UNIT_STRATEGIES:
        raise ValueError(
            f"Unknown retrieval unit strategy {retrieval_unit_strategy!r}; "
            f"expected one of {sorted(RETRIEVAL_UNIT_STRATEGIES)}"
        )
    return {
        **resolve_chunking_profile(preset),
        "retrieval_unit_strategy": retrieval_unit_strategy,
        "pdf_parser": PDF_PARSER_PROFILE.copy(),
    }


CURRENT_CHUNKING_PROFILE = resolve_corpus_profile(
    DEFAULT_CHUNKING_PROFILE_PRESET,
    "passage_hybrid",
)
