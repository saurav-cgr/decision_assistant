"""Snapshot and re-link half of a corpus rebuild (US3/T028-T031, DB40-DB43).

`coordinator.py` owns the rebuild's orchestration and its truncate scope; this
module owns the two halves that must run around that truncate:

1. `snapshot_workspace` captures, per active document, its
   id/display_name/media_type/created_at/storage_path (from its active version)
   and its decisions, each with its evidence rows (id, quote, content_hash,
   offsets).
   It runs BEFORE the truncate, because the FK's `ON DELETE SET NULL` erases
   the link the moment the document is deleted and there is no way to recover
   "which document did this decision belong to" afterward. A document with no
   active version is returned in `preserved_document_ids` instead (DB42): its
   ingestion failed or never finished, so there is nothing to re-parse, and its
   stored-file reference plus `IngestionJob` retry path are the operator's only
   record of it.

   `created_at` is captured (DB48) because the rebuild deletes and re-creates
   each `Document` row: left to its `server_default`, every re-created row
   would take the SAME `now()` — `func.now()` is the transaction timestamp, and
   the whole rebuild is one transaction — so `list_documents`'s
   `ORDER BY created_at DESC` would lose every discriminating value and hand
   back an arbitrary order where the operator had a stable, newest-first list.
   `snapshot_workspace` is ordered for the same reason: an unordered query
   drove the re-ingestion (and therefore the progress numbering and which
   document is `documents_completed: 1`) from whatever the planner happened to
   return. The order matches `list_documents` — newest first, then `id` — so a
   rebuild walks the corpus in the order the operator sees it, and ties from
   documents uploaded in one transaction resolve the same way in both places.
2. `relink_document` re-points, after the document has re-ingested, each
   snapshot's `document_version_id` at the new active version (document
   identity is preserved, so this is exact, not a guess). For each evidence
   row it first tries an identical `content_hash` chunk (the original chunk
   survived re-chunking unchanged, so the original offsets are still valid).
   Otherwise it locates the row's stored quote inside the new passages and
   re-links there with the offsets and `content_hash` of the passage it
   actually landed in (DB40: re-chunking reshapes boundaries far more often
   than it changes text, and the quote is the stable identity). Only when
   neither matches — the quote genuinely no longer exists in the rebuilt
   document — is `passage_id` left NULL with `citation_stale = true`, T031's
   originally-specified fallback. A wrong guess would misattribute evidence to
   different text, which is worse than a flagged-stale citation, so no fuzzy
   matching is used.

Split out of `coordinator.py` to keep both files under AGENTS.md's 500-line
cap: the orchestration and this snapshot/re-link pair are separate
responsibilities that change for different reasons (truncate scope vs. what
survives a re-chunk).
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.ingestion.models import Document, DocumentVersion, Passage


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    evidence_id: UUID
    quote: str | None
    content_hash: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    decision_id: UUID
    evidence: tuple[EvidenceSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    document_id: UUID
    display_name: str
    media_type: str
    storage_path: str
    # DB48: preserved onto the re-created row so `list_documents`'s
    # `created_at DESC` order survives a rebuild.
    created_at: datetime
    decisions: tuple[DecisionSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class RebuildSnapshot:
    documents: list[DocumentSnapshot]
    preserved_document_ids: list[UUID] = field(default_factory=list)


async def snapshot_workspace(
    session: AsyncSession, workspace_id: UUID
) -> RebuildSnapshot:
    """Capture what has to survive the truncate, before the truncate runs."""
    documents = list(
        await session.scalars(
            select(Document)
            .where(Document.workspace_id == workspace_id)
            # Newest first, with `id` as the tiebreaker, to match
            # `documents.service.list_documents` exactly (DB48). Documents
            # uploaded in a single transaction share one `created_at`, so
            # without the tiebreaker both this loop order and the list order
            # would depend on the plan.
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
    )
    snapshots: list[DocumentSnapshot] = []
    preserved_document_ids: list[UUID] = []
    for document in documents:
        version = (
            await session.get(DocumentVersion, document.active_version_id)
            if document.active_version_id is not None
            else None
        )
        if version is None:
            # DB42: nothing to re-ingest, and deleting the document would take
            # its stored file reference and ingestion-job retry path with it.
            preserved_document_ids.append(document.id)
            continue
        snapshots.append(
            DocumentSnapshot(
                document_id=document.id,
                display_name=document.display_name,
                media_type=document.media_type,
                storage_path=version.storage_path,
                created_at=document.created_at,
                decisions=tuple(await _snapshot_decisions(session, version.id)),
            )
        )
    return RebuildSnapshot(
        documents=snapshots, preserved_document_ids=preserved_document_ids
    )


async def _snapshot_decisions(
    session: AsyncSession, document_version_id: UUID
) -> list[DecisionSnapshot]:
    decision_ids = list(
        await session.scalars(
            select(Decision.id).where(
                Decision.document_version_id == document_version_id
            )
        )
    )
    snapshots: list[DecisionSnapshot] = []
    for decision_id in decision_ids:
        rows = (
            await session.execute(
                select(DecisionEvidence, Passage)
                .outerjoin(Passage, Passage.id == DecisionEvidence.passage_id)
                .where(DecisionEvidence.decision_id == decision_id)
            )
        ).all()
        snapshots.append(
            DecisionSnapshot(
                decision_id=decision_id,
                evidence=tuple(
                    EvidenceSnapshot(
                        evidence_id=evidence.id,
                        quote=_resolved_quote(evidence, passage),
                        content_hash=evidence.content_hash,
                        start_offset=evidence.start_offset,
                        end_offset=evidence.end_offset,
                    )
                    for evidence, passage in rows
                ),
            )
        )
    return snapshots


def _resolved_quote(
    evidence: DecisionEvidence, passage: Passage | None
) -> str | None:
    """Resolve the quote before the passage it points at is deleted.

    Rows written before revision 0016 have no stored quote, so it is sliced
    from the passage while that passage still exists. After truncation the
    only remaining identity for such a row would be an orphaned offset pair,
    which no re-link could use.
    """
    if evidence.quote is not None:
        return evidence.quote
    if passage is None:
        return None
    return passage.content[evidence.start_offset : evidence.end_offset]


def _match_evidence(
    snapshot: EvidenceSnapshot,
    by_content_hash: dict[str, Passage],
    new_passages: list[Passage],
) -> tuple[Passage, int, int] | None:
    """Find the rebuilt passage (and offsets) an evidence row belongs to.

    Identical chunk first: the passage content is byte-identical, so the
    original offsets still address the same quote. Otherwise the stored quote
    is located inside the reshaped passages; the row then takes the offsets of
    where the quote actually landed. No fuzzy matching (see the module
    docstring).
    """
    matching_passage = by_content_hash.get(snapshot.content_hash)
    if matching_passage is not None:
        return matching_passage, snapshot.start_offset, snapshot.end_offset
    if not snapshot.quote:
        return None
    for candidate in new_passages:
        position = candidate.content.find(snapshot.quote)
        if position >= 0:
            return candidate, position, position + len(snapshot.quote)
    return None


async def relink_document(
    session: AsyncSession,
    document_snapshot: DocumentSnapshot,
    new_version_id: UUID,
) -> None:
    if not document_snapshot.decisions:
        return
    new_passages = list(
        await session.scalars(
            select(Passage)
            .where(Passage.document_version_id == new_version_id)
            .order_by(Passage.sequence_number)
        )
    )
    by_content_hash: dict[str, Passage] = {}
    for passage in new_passages:
        by_content_hash.setdefault(passage.content_hash, passage)

    for decision_snapshot in document_snapshot.decisions:
        decision = await session.get(Decision, decision_snapshot.decision_id)
        if decision is None:
            continue
        decision.document_version_id = new_version_id
        for evidence_snapshot in decision_snapshot.evidence:
            evidence = await session.get(
                DecisionEvidence, evidence_snapshot.evidence_id
            )
            if evidence is None:
                continue
            matched = _match_evidence(evidence_snapshot, by_content_hash, new_passages)
            if matched is None:
                evidence.passage_id = None
                evidence.citation_stale = True
                continue
            passage, start_offset, end_offset = matched
            evidence.passage_id = passage.id
            evidence.start_offset = start_offset
            evidence.end_offset = end_offset
            # Keep the row coherent with the passage it now points at: the
            # correction API rejects a client-supplied hash that does not
            # match the passage (decisions/service.py's `_validate_evidence`),
            # and it echoes this column back to the client.
            evidence.content_hash = passage.content_hash
            if evidence.quote is None:
                evidence.quote = evidence_snapshot.quote
            evidence.citation_stale = False
    await session.flush()
