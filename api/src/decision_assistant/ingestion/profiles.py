"""Centralized corpus chunking-profile contract.

The current schema generation stores a single non-null
``structural-token-v1`` chunking profile on every ``DocumentVersion``. There is
no legacy profile and no in-place migration path: changing chunking or embedding
contracts requires an explicit database reset and complete reingestion while the
project remains under development policy.
"""

CURRENT_CHUNKING_PROFILE: dict[str, object] = {
    "algorithm": "structural-token-v1",
    "encoding": "cl100k_base",
    "target_tokens": 450,
    "max_tokens": 600,
    "overlap_tokens": 60,
}
