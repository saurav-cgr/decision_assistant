"""Workspace-scoped embedding cache resolution.

Split out of `ingestion/service.py` (DB67): the service owns the document/version/job lifecycle,
this module owns the question "which of these chunk texts still need an embedding call?".

The cache is keyed by workspace, embedding-profile fingerprint and content hash, so re-ingesting
identical text with the same provider costs no embedding calls. Only misses go to the provider, and
each new vector is stored so the next document — and a later rebuild — can reuse it.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.ingestion.errors import IngestionError
from decision_assistant.ingestion.models import EmbeddingCache
from decision_assistant.ingestion.retrieval_units import RetrievalUnitDraft
from decision_assistant.providers.base import EmbeddingProvider, EmbeddingPurpose
from decision_assistant.workspace.embedding_profile import embedding_profile_fingerprint


async def resolve_embedding_cache(
    session: AsyncSession,
    *,
    embedding_provider: EmbeddingProvider,
    workspace_id: UUID,
    unit_drafts: list[RetrievalUnitDraft],
) -> dict[str, EmbeddingCache]:
    """Return every draft's content hash mapped to a cached (or freshly stored) embedding row."""
    profile = embedding_provider.profile
    fingerprint = embedding_profile_fingerprint(profile)
    content_hashes = list(dict.fromkeys(unit.draft.content_hash for unit in unit_drafts))
    existing = list(
        await session.scalars(
            select(EmbeddingCache).where(
                EmbeddingCache.workspace_id == workspace_id,
                EmbeddingCache.embedding_profile_fingerprint == fingerprint,
                EmbeddingCache.content_hash.in_(content_hashes),
            )
        )
    )
    by_hash = {entry.content_hash: entry for entry in existing}
    missing = [
        unit.draft
        for unit in unit_drafts
        if unit.draft.content_hash not in by_hash
    ]
    missing = list({draft.content_hash: draft for draft in missing}.values())
    if missing:
        vectors = await embedding_provider.embed(
            [draft.content for draft in missing],
            purpose=EmbeddingPurpose.DOCUMENT,
        )
        if len(vectors) != len(missing):
            raise IngestionError(
                "Embedding provider returned wrong result count",
                code="embedding_count_mismatch",
            )
        for draft, vector in zip(missing, vectors, strict=True):
            entry = EmbeddingCache(
                workspace_id=workspace_id,
                content_hash=draft.content_hash,
                embedding_profile_fingerprint=fingerprint,
                embedding_profile=profile.as_dict(),
                embedding=vector,
            )
            session.add(entry)
            by_hash[draft.content_hash] = entry
        await session.flush()
    return by_hash
