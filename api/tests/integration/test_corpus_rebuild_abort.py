"""DB43: a rebuild that fails partway keeps the old corpus (human option A).

Checker V118 reproduced the pre-DB43 behaviour live: a rebuild against an
invalid provider key finished `failed 0/7` but had already committed the
truncation, so the workspace was left with zero passages, eight documents
without an active version, twenty decisions with nulled document/passage links
(and no `citation_stale` flag), and no working retry path — the next snapshot
excluded those documents (DB42) and a per-document retry re-extracted duplicate
decisions.

Now a per-document re-ingestion failure raises `RebuildAborted` while the
corpus transaction is still open; `dispatch._run` rolls that transaction back
and only marks the separately-committed `CorpusRebuild` row failed. These tests
prove the two halves: the old corpus and the decision/evidence links survive,
the failure is recorded with the underlying provider error code, and a retry
after the provider recovers succeeds from that intact data.

The same rollback makes the row's `documents_completed` a lie unless it is
reset, so every failure path writes `documents_completed: 0` (DB43's human
finding, DB44's checker finding). The abort test asserts the row really was
mid-flight at `1/2` before the failure, and a second test drives the systemic
(non-abort) path the same way; the interrupted-row sweep is covered in
`test_corpus_rebuild_progress.py`.

Multi-transaction by necessity (the abort happens inside the dispatcher's own
session), so this file opens its own engine/sessions like
`test_corpus_rebuild_progress.py` and deletes what it commits (M-037).

The source documents and the outage provider live in
`tests/support/corpus_rebuild_fixtures.py`, so this file stays under the
AGENTS.md 500-line cap.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from decision_assistant.config import Settings
from decision_assistant.db import create_engine
from decision_assistant.decisions.extractor import DecisionExtractor
from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.models import (
    Document,
    DocumentVersion,
    IngestionJob,
    Passage,
)
from decision_assistant.ingestion.service import IngestionService
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)
from decision_assistant.workspace.models import Workspace
from decision_assistant.workspace.rebuild.dispatch import dispatch_corpus_rebuild
from decision_assistant.workspace.rebuild_models import CorpusRebuild
from tests.support.corpus_rebuild_fixtures import (
    METADATA_RESPONSE,
    QUOTED_SENTENCE,
    SOURCE_TEXT,
    SOURCE_TEXT_2,
    OutageEmbeddingProvider,
    rebuild_providers,
)


async def _seed_active_document_with_decision(factory, tmp_path: Path):  # noqa: ANN001, ANN201
    """Ingest a real document, then attach a decision/evidence pair to it.

    Hand-attached rather than extracted, matching
    `test_corpus_rebuild_run.py`: a rebuild redispatch passes
    `extract_decisions=False`, so the preserved row is the sole record and any
    duplication would be visible as a second `Decision` row.
    """
    workspace_id = uuid4()
    document_id = uuid4()
    upload_directory = tmp_path / "uploads"
    source_path = tmp_path / "source" / "meeting.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(SOURCE_TEXT, encoding="utf-8")

    async with factory() as session:
        session.add(Workspace(id=workspace_id, name=f"Abort {workspace_id}"))
        await session.flush()
        session.add(
            Document(
                id=document_id,
                workspace_id=workspace_id,
                display_name="meeting.md",
                media_type="text/markdown",
            )
        )
        await session.flush()
        service = IngestionService(
            session=session,
            embedding_provider=FakeEmbeddingProvider(dimension=768),
            decision_extractor=DecisionExtractor(FakeGenerationProvider()),
            metadata_extractor=MetadataExtractor(
                FakeGenerationProvider([METADATA_RESPONSE, METADATA_RESPONSE])
            ),
            upload_directory=upload_directory,
        )
        result = await service.ingest(
            document_id,
            source_path,
            request_id=str(uuid4()),
            job_id=None,
            extract_decisions=False,
        )
        await session.flush()

        passage = next(
            p
            for p in await session.scalars(
                select(Passage).where(Passage.document_version_id == result.version_id)
            )
            if QUOTED_SENTENCE in p.content
        )
        start_offset = passage.content.find(QUOTED_SENTENCE)

        decision = Decision(
            workspace_id=workspace_id,
            document_version_id=result.version_id,
            statement="Authentication was postponed.",
            status="active",
            provenance="extracted",
            review_state="supported",
        )
        session.add(decision)
        await session.flush()
        evidence = DecisionEvidence(
            decision_id=decision.id,
            passage_id=passage.id,
            start_offset=start_offset,
            end_offset=start_offset + len(QUOTED_SENTENCE),
            content_hash=passage.content_hash,
            quote=QUOTED_SENTENCE,
        )
        session.add(evidence)

        # A second document with no decision: it exists to be a document that
        # succeeds before the next one fails, which is what makes the
        # "discarded progress is not reported" assertion meaningful.
        second_document_id = uuid4()
        source_path_2 = tmp_path / "source" / "second.md"
        source_path_2.write_text(SOURCE_TEXT_2, encoding="utf-8")
        session.add(
            Document(
                id=second_document_id,
                workspace_id=workspace_id,
                display_name="second.md",
                media_type="text/markdown",
            )
        )
        await session.flush()
        second = await service.ingest(
            second_document_id,
            source_path_2,
            request_id=str(uuid4()),
            job_id=None,
            extract_decisions=False,
        )
        await session.commit()

        return {
            "workspace_id": workspace_id,
            "document_id": document_id,
            "document_id_2": second_document_id,
            "upload_directory": upload_directory,
            "version_id": result.version_id,
            "version_id_2": second.version_id,
            "passage_id": passage.id,
            "decision_id": decision.id,
            "evidence_id": evidence.id,
        }


@pytest.mark.asyncio
async def test_failed_rebuild_rolls_back_and_stays_retryable(tmp_path: Path) -> None:
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seed = await _seed_active_document_with_decision(factory, tmp_path)
    workspace_id = seed["workspace_id"]
    settings = Settings(upload_directory=seed["upload_directory"])
    started = asyncio.Event()
    release = asyncio.Event()
    try:
        task = asyncio.create_task(
            dispatch_corpus_rebuild(
                factory,
                workspace_id=workspace_id,
                reason="corpus_reset_required",
                settings=settings,
                providers=rebuild_providers(
                    embedding=OutageEmbeddingProvider(started, release)
                ),
                request_id=str(uuid4()),
            )
        )
        try:
            # Held inside the second document's embedding: the first document
            # has finished and committed its progress, so the row must be
            # visibly mid-flight here. This is the assertion DB44 asked for —
            # without it the final `0` could pass for the wrong reason (no
            # progress ever committed).
            await asyncio.wait_for(started.wait(), timeout=30)
            async with factory() as observer:
                in_flight = await observer.scalar(
                    select(CorpusRebuild).where(
                        CorpusRebuild.workspace_id == workspace_id
                    )
                )
                assert in_flight is not None
                assert in_flight.status == "running"
                assert in_flight.documents_total == 2
                assert in_flight.documents_completed == 1, (
                    "the running row should show the one document that finished: "
                    f"{in_flight.documents_completed}/{in_flight.documents_total}"
                )
            release.set()
            await asyncio.wait_for(task, timeout=60)
        finally:
            release.set()
            if not task.done():
                task.cancel()

        async with factory() as session:
            rebuild = await session.scalar(
                select(CorpusRebuild).where(CorpusRebuild.workspace_id == workspace_id)
            )
            assert rebuild is not None
            assert rebuild.status == "failed"
            # Which of the two documents fails depends on the snapshot's
            # iteration order (unspecified), so only the code and the fact that
            # the row names one of the fixture's documents are asserted.
            assert rebuild.error is not None
            assert rebuild.error["code"] == "provider_unavailable"
            assert rebuild.error["document_id"] in {
                str(seed["document_id"]),
                str(seed["document_id_2"]),
            }
            assert rebuild.documents_total == 2
            assert rebuild.documents_completed == 0
            assert rebuild.finished_at is not None

            # The truncation must be gone with the transaction (DB43): the
            # old corpus is exactly as it was.
            for document_id, version_id in (
                (seed["document_id"], seed["version_id"]),
                (seed["document_id_2"], seed["version_id_2"]),
            ):
                document = await session.get(Document, document_id)
                assert document is not None, "the document was destroyed by the abort"
                assert document.active_version_id == version_id

                version = await session.get(DocumentVersion, version_id)
                assert version is not None
                assert version.state == "active"

                passages = list(
                    await session.scalars(
                        select(Passage).where(Passage.document_version_id == version_id)
                    )
                )
                assert passages, "the passages were destroyed by the abort"

                # The abort never committed a second version.
                versions = list(
                    await session.scalars(
                        select(DocumentVersion).where(
                            DocumentVersion.document_id == document_id
                        )
                    )
                )
                assert [v.id for v in versions] == [version_id]

            decision = await session.get(Decision, seed["decision_id"])
            assert decision is not None
            assert decision.document_version_id == seed["version_id"]

            evidence = await session.get(DecisionEvidence, seed["evidence_id"])
            assert evidence is not None
            assert evidence.passage_id == seed["passage_id"]
            assert evidence.citation_stale is False

        # Retry after the provider recovers re-runs against the intact corpus
        # instead of finishing `completed 0/0` (V118).
        await dispatch_corpus_rebuild(
            factory,
            workspace_id=workspace_id,
            reason="manual_retry",
            settings=settings,
            providers=rebuild_providers(embedding=FakeEmbeddingProvider(dimension=768)),
            request_id=str(uuid4()),
        )

        async with factory() as session:
            retried = list(
                await session.scalars(
                    select(CorpusRebuild)
                    .where(CorpusRebuild.workspace_id == workspace_id)
                    .order_by(CorpusRebuild.created_at)
                )
            )
            assert retried[-1].status == "completed"
            assert retried[-1].documents_total == 2
            assert retried[-1].documents_completed == 2

            new_version_ids = {}
            for document_id in (seed["document_id"], seed["document_id_2"]):
                document = await session.get(Document, document_id)
                assert document is not None
                active = document.active_version_id
                assert active is not None
                new_version_ids[document_id] = active
            assert new_version_ids[seed["document_id"]] != seed["version_id"]
            assert new_version_ids[seed["document_id_2"]] != seed["version_id_2"]

            decision = await session.get(Decision, seed["decision_id"])
            assert decision is not None
            assert decision.document_version_id == new_version_ids[seed["document_id"]]

            # No duplicate decision was extracted by the rebuild redispatch.
            decisions = list(
                await session.scalars(
                    select(Decision).where(Decision.workspace_id == workspace_id)
                )
            )
            assert [d.id for d in decisions] == [seed["decision_id"]]

            evidence = await session.get(DecisionEvidence, seed["evidence_id"])
            assert evidence is not None
            assert evidence.passage_id is not None
            assert evidence.citation_stale is False

            for document_id in (seed["document_id"], seed["document_id_2"]):
                jobs = list(
                    await session.scalars(
                        select(IngestionJob).where(
                            IngestionJob.document_id == document_id
                        )
                    )
                )
                assert len(jobs) == 1, (
                    "the aborted attempt left an ingestion job behind: "
                    f"{document_id} has {len(jobs)}"
                )
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                delete(Workspace).where(Workspace.id == workspace_id)
            )
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_systemic_failure_row_reports_no_discarded_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB44 path 2: a non-`RebuildAborted` failure must also read 0 completed.

    `execute_rebuild` itself is replaced, because a systemic failure
    (snapshot/truncate/redispatch) is not reachable deterministically from the
    outside — but the shape that matters is preserved: the progress hook
    commits that a document finished, and *then* the rebuild dies. Before
    DB44's fix this path kept that committed count on the `failed` row.
    """
    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seed = await _seed_active_document_with_decision(factory, tmp_path)
    workspace_id = seed["workspace_id"]

    async def _fail_after_progress(*_args: object, progress=None, **_kwargs: object):
        assert progress is not None
        await progress(
            {"status": "running", "documents_total": 2, "documents_completed": 1}
        )
        raise RuntimeError("snapshot exploded")

    monkeypatch.setattr(
        "decision_assistant.workspace.rebuild.dispatch.execute_rebuild",
        _fail_after_progress,
    )

    try:
        await dispatch_corpus_rebuild(
            factory,
            workspace_id=workspace_id,
            reason="corpus_reset_required",
            settings=Settings(upload_directory=seed["upload_directory"]),
            providers=rebuild_providers(embedding=FakeEmbeddingProvider(dimension=768)),
            request_id=str(uuid4()),
        )

        async with factory() as session:
            rebuild = await session.scalar(
                select(CorpusRebuild).where(
                    CorpusRebuild.workspace_id == workspace_id
                )
            )
            assert rebuild is not None
            assert rebuild.status == "failed"
            assert rebuild.error == {"code": "rebuild_failed"}
            assert rebuild.finished_at is not None
            assert rebuild.documents_completed == 0, (
                "a failed row must not report the progress it rolled back: "
                f"{rebuild.documents_completed}/{rebuild.documents_total}"
            )

            # The corpus is intact, exactly as on the abort path.
            for document_id, version_id in (
                (seed["document_id"], seed["version_id"]),
                (seed["document_id_2"], seed["version_id_2"]),
            ):
                document = await session.get(Document, document_id)
                assert document is not None
                assert document.active_version_id == version_id
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                delete(Workspace).where(Workspace.id == workspace_id)
            )
            await cleanup.commit()
        await engine.dispose()
