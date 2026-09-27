"""Corpus rebuild orchestration for a workspace (US3/T028-T031).

`truncate_corpus_derived_tables` deletes `documents, document_versions,
passages, embedding_cache, ingestion_jobs` and never the non-derived tables
(`decisions`, `decision_evidence`, `decision_relations`, `decision_revisions`,
`conversations`, ...). `decisions.workspace_id` (DB38, revision 0015) and
`decisions.document_version_id`/`decision_evidence.passage_id` (`ON DELETE
SET NULL`, DB34, revision 0014) mean those rows survive with a nulled
reference, still visible in their workspace, rather than cascading away.

`retrieval_traces` is deliberately EXCLUDED from this scope (DB38's sibling,
DB37): it was originally listed in data-model.md as corpus-derived, but
`conversation_messages.trace_id`/`question_answers.trace_id` are `ON DELETE
CASCADE` from it, so deleting it destroys every conversation turn — exactly
what D7 requires to survive. `retrieval_traces` has no FK to `passages` or
`document_versions` (`selected_passage_ids` is plain JSONB, not a foreign
key), so leaving stale trace rows in place after a rebuild is harmless; it is
reclassified as non-derived (see data-model.md).

A document with no active version is PRESERVED, not truncated (DB42): its
ingestion failed or never finished, so there is nothing to re-parse, and its
stored-file reference plus `IngestionJob` retry path are the operator's only
record of it (spec US3: documents survive the upgrade).

`execute_rebuild` is the full end-to-end orchestration:

1. `relink.py`'s `snapshot_workspace` captures what has to survive the
   truncate (document identity, storage path, and each decision's evidence
   with its stored quote) while the links still resolve.
2. Truncate the corpus-derived rows of the active documents (DB42), keeping
   the preserved ones.
3. Recreate each active document with the SAME id and re-dispatch the
   existing ingestion pipeline against its original stored file, with
   `extract_decisions=False` (DB40 human decision): a rebuild re-chunks and
   re-embeds to fix `corpus_reset_required`, it must not re-extract a second,
   duplicate decision set from the same document — the preserved decisions
   are the sole record (D7 requires them "unchanged").
4. `relink.py`'s `relink_document` re-points each surviving decision at the
   document's new active version and re-matches its evidence to a rebuilt
   passage (identical `content_hash` first, then the stored quote; `NULL` +
   `citation_stale` when neither matches). Both halves and their reasoning
   live in that module's docstring.

`execute_rebuild` reports progress only through an injected `ProgressHook`
(DB41). Direct callers (`run_corpus_rebuild`) pass an in-session hook, so the
`CorpusRebuild` row lives in the same transaction as the corpus work. The
background dispatchers (`workspace/rebuild/dispatch.py`) pass a hook that
commits each update in its OWN session, because otherwise the row (and its
progress) is invisible to every other session until the whole rebuild
commits — quickstart.md Section 4's polling step would report the previous
run's state, and FR-006/T032's progress UI would have nothing to show.
Committing per document instead would break the guarantee V108 relies on
(readers keep seeing the old corpus until the rebuild commits).

A document whose re-ingestion fails ABORTS the whole rebuild (DB43): the
failure is raised as `RebuildAborted` while the corpus transaction is still
uncommitted, so the truncation, the re-created documents and every re-link are
discarded and the workspace keeps its old, intact corpus. Continuing past the
failure (the pre-DB43 behaviour) committed an emptied corpus — documents
without active versions, decisions with nulled document/passage links and no
`citation_stale` flag, and no retry path back, because the DB42 preserve rule
then excluded those documents from the next snapshot (checker V118, live).
The `CorpusRebuild` row's owner (`workspace/rebuild/dispatch.py`) rolls the
transaction back and records `failed` with the offending document's error
code, so T030's retry re-runs against real data.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.documents.storage import LocalFileStorage
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.models import Document, EmbeddingCache
from decision_assistant.ingestion.profiles import resolve_corpus_profile
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.providers.factory import ProviderBundle
from decision_assistant.workspace.rebuild.relink import (
    relink_document,
    snapshot_workspace,
)
from decision_assistant.workspace.rebuild_models import CorpusRebuild

# A progress hook receives the fields to write onto the `CorpusRebuild` row.
# See the module docstring: the background dispatchers commit each update in
# its own session; direct callers mutate the row in the caller's session.
ProgressHook = Callable[[dict[str, Any]], Awaitable[None]]


class RebuildAborted(RuntimeError):
    """A per-document failure that aborts and rolls back the whole rebuild.

    Re-ingesting a document makes provider calls that fail for systemic
    reasons (an invalid or unreachable provider key, an outage). Committing
    the rebuild anyway destroys the corpus the operator still needs (DB43), so
    the failure is propagated instead and the transaction is discarded.
    `error` is the dict to record on the `CorpusRebuild` row.
    """

    def __init__(self, error: dict[str, object]) -> None:
        super().__init__(str(error.get("code", "rebuild_aborted")))
        self.error = error


async def _emit(progress: ProgressHook | None, fields: dict[str, Any]) -> None:
    if progress is not None:
        await progress(fields)


async def truncate_corpus_derived_tables(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    preserve_document_ids: Sequence[UUID] = (),
) -> None:
    """Delete a workspace's corpus-derived rows, leaving decisions/evidence intact.

    Deleting `Document` cascades (`ON DELETE CASCADE`, enforced by Postgres,
    not the ORM) to `document_versions`, `passages`, and `ingestion_jobs`.
    `embedding_cache` is workspace-scoped directly with no cascade path from
    `documents`, so it is deleted separately. `preserve_document_ids` carries
    the documents a rebuild could not re-ingest (DB42: no active version) —
    deleting those would destroy the document's stored-file reference and its
    retry path with nothing to recreate them from. Caller commits; this only
    issues the deletes on the given session.
    """
    document_delete = delete(Document).where(Document.workspace_id == workspace_id)
    if preserve_document_ids:
        document_delete = document_delete.where(Document.id.notin_(preserve_document_ids))
    await session.execute(document_delete)
    await session.execute(
        delete(EmbeddingCache).where(EmbeddingCache.workspace_id == workspace_id)
    )


def _in_session_progress(
    session: AsyncSession, rebuild: CorpusRebuild
) -> ProgressHook:
    """Progress hook for a caller that owns the whole rebuild transaction.

    The `CorpusRebuild` row and the corpus work share one transaction here, so
    the hook only mutates and flushes the row in place (no separate commit is
    possible without breaking the transaction). Used by `run_corpus_rebuild`
    and the tests that drive it directly; the background dispatchers use
    `workspace/rebuild/dispatch.py`'s committing hook (DB41).
    """

    async def hook(fields: dict[str, Any]) -> None:
        for key, value in fields.items():
            setattr(rebuild, key, value)
        await session.flush()

    return hook


async def run_corpus_rebuild(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    reason: str,
    settings: object,
    providers: ProviderBundle,
    request_id: str,
) -> CorpusRebuild:
    """Create a fresh `CorpusRebuild` row and run it; caller commits.

    Propagates `RebuildAborted` (DB43) when a document fails to re-ingest. The
    row is created in this same transaction, so the caller's rollback discards
    it too — a direct caller that wants a durable `failed` row must record it
    itself, the way `workspace/rebuild/dispatch.py` does in its own session.

    `settings` is `decision_assistant.config.Settings`, typed loosely here to
    avoid an import cycle with `workspace.embedding_profile`.
    """
    rebuild = CorpusRebuild(
        workspace_id=workspace_id,
        status="pending",
        reason=reason,
        documents_total=0,
        documents_completed=0,
    )
    session.add(rebuild)
    await session.flush()
    await execute_rebuild(
        session,
        workspace_id=workspace_id,
        progress=_in_session_progress(session, rebuild),
        settings=settings,
        providers=providers,
        request_id=request_id,
    )
    return rebuild


async def execute_rebuild(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    progress: ProgressHook | None,
    settings: object,
    providers: ProviderBundle,
    request_id: str,
) -> None:
    """Snapshot, truncate, re-ingest, and re-link one workspace's corpus.

    Never touches the `CorpusRebuild` row directly — every status/progress
    change goes through `progress`, so the background dispatchers can commit
    it in a separate session while this transaction stays open (DB41).
    """
    snapshot = await snapshot_workspace(session, workspace_id)
    completed = 0
    await _emit(
        progress,
        {
            "status": "running",
            "documents_total": len(snapshot.documents),
            "documents_completed": 0,
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
            "error": None,
        },
    )

    await truncate_corpus_derived_tables(
        session,
        workspace_id,
        preserve_document_ids=snapshot.preserved_document_ids,
    )
    await session.flush()

    storage = LocalFileStorage(settings.upload_directory)
    ingestion_service = IngestionService(
        session=session,
        embedding_provider=providers.embedding,
        decision_extractor=DecisionExtractor(
            providers.generation,
            max_prompt_characters=settings.gemini_max_prompt_characters,
        ),
        metadata_extractor=MetadataExtractor(providers.generation),
        upload_directory=settings.upload_directory,
        chunking_profile=resolve_corpus_profile(
            settings.chunking_profile_preset,
            settings.retrieval_unit_strategy,
        ),
        retrieval_unit_strategy=settings.retrieval_unit_strategy,
    )

    for document_snapshot in snapshot.documents:
        new_document = Document(
            id=document_snapshot.document_id,
            workspace_id=workspace_id,
            display_name=document_snapshot.display_name,
            media_type=document_snapshot.media_type,
            # Carry the original timestamp onto the re-created row (DB48).
            # `created_at` is a `server_default`, so omitting it would give
            # every re-created document the SAME `now()` (one transaction, one
            # transaction timestamp), leaving `list_documents`'s
            # `ORDER BY created_at DESC` with nothing to sort by — the list
            # would come back in an arbitrary order after a rebuild, and every
            # document would read as uploaded just now.
            created_at=document_snapshot.created_at,
        )
        session.add(new_document)
        await session.flush()
        original_path = storage.local_path(document_snapshot.storage_path)
        try:
            # `ingest()`'s new-document path always copies its source into a
            # freshly computed `{document_id}/v{n}-{checksum}` destination
            # (`_store_source`). Since a rebuild deliberately reuses the same
            # `document_id` and this is that document's first version again,
            # that destination can collide with `original_path` itself
            # (`shutil.copyfile` refuses to copy a file onto itself) whenever
            # the source is unchanged. Ingest from a disposable copy instead.
            with TemporaryDirectory() as scratch_directory:
                scratch_path = Path(scratch_directory) / original_path.name
                copyfile(original_path, scratch_path)
                result = await ingestion_service.ingest(
                    document_snapshot.document_id,
                    scratch_path,
                    request_id=request_id,
                    job_id=None,
                    extract_decisions=False,
                )
        except Exception as exc:  # noqa: BLE001 - translated to RebuildAborted below
            # DB43: the transaction is abandoned with the old corpus still in
            # place. The docstring above and `RebuildAborted` explain why.
            raise RebuildAborted(
                {
                    "code": getattr(exc, "code", "ingestion_failed"),
                    "document_id": str(document_snapshot.document_id),
                }
            ) from exc
        await relink_document(session, document_snapshot, result.version_id)
        completed += 1
        await session.flush()
        await _emit(progress, {"documents_completed": completed})

    await _emit(
        progress,
        {
            "status": "completed",
            "documents_completed": completed,
            "error": None,
            "finished_at": datetime.now(timezone.utc),
        },
    )
