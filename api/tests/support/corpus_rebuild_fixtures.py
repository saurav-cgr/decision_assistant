"""Shared fixtures for the corpus-rebuild integration tests.

Two source documents and a provider that stages an outage mid-rebuild. The
first document carries a decision and its evidence; the second exists to
complete first, which is what lets a test prove an aborted rebuild does not
keep claiming progress it rolled back (DB44).
"""

import asyncio

from decision_assistant.providers.base import ProviderUnavailable
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)

METADATA_RESPONSE = {
    "title": "Architecture Sync",
    "document_date": "2026-07-15",
    "participants": ["Maya", "Ravi"],
    "source_type": "meeting",
    "project": "Atlas",
}

SOURCE_TEXT = """---
title: Architecture Sync
date: 2026-07-15
participants: [Maya, Ravi]
source_type: meeting
project: Atlas
---

# Authentication

Authentication was postponed until the import flow is stable.
"""

QUOTED_SENTENCE = "Authentication was postponed until the import flow is stable."

# The second document must share no chunk *content* with the first (DB49) —
# stricter than merely differing. A rebuild truncates `embedding_cache` first,
# so the first document re-embeds and repopulates it; a later document whose
# chunk text is byte-identical is then served entirely from that cache
# (`IngestionService._resolve_embedding_cache` asks the provider only for the
# hashes it is missing), the staged outage below never fires, and the test dies
# in `started.wait()`. Which document is processed first is decided by random
# uuids (DB48), so this fixture must hold for either order.
SOURCE_TEXT_2 = """---
title: Rollout Plan
date: 2026-07-18
participants: [Ravi]
source_type: meeting
project: Atlas
---

# Rollout

The rollout starts the week after the import flow lands, gated on the stability review.
"""


class OutageEmbeddingProvider(FakeEmbeddingProvider):
    """Fails on its second document's embedding, after signalling the moment.

    Failing on the *second* call is deliberate: it lets the first document
    complete and its progress commit, so the test can prove the aborted row
    does not keep claiming that discarded progress. The test waits for
    `started` and reads the rebuild row from another session *while the rebuild
    is held there*, which pins the two things an earlier version of this test
    only assumed: that an intermediate `documents_completed: 1` is really
    committed, and that one `embed` call happens per document (DB44's note).
    """

    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(dimension=768)
        self._started = started
        self._release = release
        self.calls = 0

    async def embed(self, texts, *, purpose):  # noqa: ANN001, ANN201 - provider protocol
        self.calls += 1
        if self.calls > 1:
            self._started.set()
            await self._release.wait()
            raise ProviderUnavailable("provider outage")
        return await super().embed(texts, purpose=purpose)


def rebuild_providers(*, embedding) -> ProviderBundle:  # noqa: ANN001 - test helper
    return ProviderBundle(
        embedding=embedding,
        # One metadata response per document (two documents in this fixture).
        generation=FakeGenerationProvider([METADATA_RESPONSE, METADATA_RESPONSE]),
    )
