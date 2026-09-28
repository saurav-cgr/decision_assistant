"""T034: a real backup/restore round trip (quickstart.md Section 5, D8).

`api/tests/unit/test_backup.py` covers the archive layout with a faked
`pg_dump`. This test uses the real binaries the production image ships: a live
`pg_dump` of the test database is taken through `create_pre_migration_backup`,
the seeded rows and the upload files are then deleted (the in-container
equivalent of wiping the data volumes), and the archive is restored with
`psql -v ON_ERROR_STOP=1` — the same invocation `scripts/restore.sh` pipes the
dump into. Row counts for every application table and the upload file
contents must match the pre-backup state afterwards.

Scope note: `scripts/restore.sh` itself shells out to `docker compose exec`,
which the api container cannot reach (DB22, the same reason the in-container
backup half was written separately), so the *host-side* script path is verified
by quickstart.md Section 5 and, once T070 lands, by CI — not here. Everything
below the script boundary (the archive layout the script reads, and the psql
restore it performs) is exercised for real.
"""

import asyncio
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_assistant import backup
from decision_assistant.answering.conversation_models import (
    Conversation,
    ConversationMessage,
)
from decision_assistant.answering.schemas import (
    AnswerState,
    ConfidenceCategory,
    QuestionResponse,
)
from decision_assistant.config import Settings, get_settings
from decision_assistant.db import create_engine
from decision_assistant.decisions.models import Decision, DecisionEvidence
from decision_assistant.ingestion.models import Document, DocumentVersion, Passage
from decision_assistant.retrieval.models import RetrievalTrace
from decision_assistant.workspace.models import Workspace

_QUOTE = "Authentication was postponed until the import flow is stable."

# Every application table quickstart Section 5's "data matches before backup and
# after restore" claim covers. Counted globally, because the restore replaces
# the whole database: a `pg_dump --clean --if-exists` restore is not scoped to
# one workspace.
_TABLES = (
    "workspaces",
    "documents",
    "document_versions",
    "passages",
    "decisions",
    "decision_evidence",
    "conversations",
    "conversation_messages",
    "retrieval_traces",
)


async def _counts(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with factory() as session:
        counts: dict[str, int] = {}
        for table in _TABLES:
            # Fixed literal table list, never user input (AGENTS.md's SQL rule).
            counts[table] = int(
                await session.scalar(text(f"SELECT count(*) FROM {table}")) or 0
            )
        return counts


def _upload_files(upload_directory: Path) -> list[str]:
    return sorted(
        str(path.relative_to(upload_directory))
        for path in upload_directory.rglob("*")
        if path.is_file()
    )


async def _seed(factory: async_sessionmaker[AsyncSession]) -> dict:
    workspace_id = uuid4()
    conversation_id = uuid4()
    async with factory() as session:
        session.add(Workspace(id=workspace_id, name=f"Backup {workspace_id}"))
        await session.flush()
        document = Document(
            workspace_id=workspace_id,
            display_name="doc.txt",
            media_type="text/plain",
        )
        session.add(document)
        await session.flush()
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            checksum="checksum",
            storage_path="doc.txt",
            state="active",
        )
        session.add(version)
        await session.flush()
        document.active_version_id = version.id
        passage = Passage(
            document_version_id=version.id,
            sequence_number=0,
            content=f"Intro. {_QUOTE}",
            start_offset=0,
            end_offset=len(_QUOTE) + 7,
            content_hash="hash",
            locator={"kind": "line", "line": 1},
            embedding=None,
        )
        session.add(passage)
        await session.flush()
        decision = Decision(
            workspace_id=workspace_id,
            document_version_id=version.id,
            statement="Authentication was postponed.",
            status="active",
            provenance="extracted",
            review_state="supported",
        )
        session.add(decision)
        await session.flush()
        session.add(
            DecisionEvidence(
                decision_id=decision.id,
                passage_id=passage.id,
                start_offset=7,
                end_offset=7 + len(_QUOTE),
                content_hash="hash",
                quote=_QUOTE,
            )
        )
        trace = RetrievalTrace(
            workspace_id=workspace_id,
            request_id="t034-seed",
            normalized_question="When was authentication postponed?",
        )
        session.add(trace)
        session.add(
            Conversation(id=conversation_id, workspace_id=workspace_id, title="Auth")
        )
        await session.flush()
        session.add(
            ConversationMessage(
                conversation_id=conversation_id,
                trace_id=trace.id,
                turn_number=1,
                question="When was authentication postponed?",
                response=QuestionResponse(
                    answer="After the import flow stabilised.",
                    state=AnswerState.ANSWERED,
                    confidence=ConfidenceCategory.HIGH,
                    trace_id=trace.id,
                ).model_dump(mode="json"),
                response_schema_version=1,
                knowledge_revision=1,
                created_at=datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
            )
        )
        await session.commit()
        return {
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
            "decision_id": decision.id,
        }


@pytest.mark.asyncio
async def test_backup_then_volume_wipe_then_restore_matches_counts_and_files(
    tmp_path: Path,
) -> None:
    settings = get_settings()
    upload_directory = tmp_path / "uploads"
    backup_directory = tmp_path / "backups"
    upload_directory.mkdir(parents=True)
    (upload_directory / "doc.txt").write_text("stored file", encoding="utf-8")
    nested = upload_directory / "sub"
    nested.mkdir()
    (nested / "nested.txt").write_text("nested file", encoding="utf-8")

    engine = create_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    seed = await _seed(factory)
    before = await _counts(factory)
    files_before = _upload_files(upload_directory)
    assert before["conversation_messages"] >= 1

    # Close pooled connections before `psql` runs the dump's DROP statements.
    await engine.dispose()

    archive = await asyncio.to_thread(
        backup.create_pre_migration_backup,
        Settings(
            backup_directory=backup_directory,
            upload_directory=upload_directory,
        ),
    )
    try:
        # The wipe: delete the seeded workspace (cascades to its documents,
        # versions, passages, decisions, evidence, conversations) and remove
        # the upload files, standing in for a deleted data volume.
        wipe_engine = create_engine()
        wipe_factory = async_sessionmaker(wipe_engine, expire_on_commit=False)
        async with wipe_factory() as session:
            await session.execute(
                delete(Workspace).where(Workspace.id == seed["workspace_id"])
            )
            await session.commit()
        await wipe_engine.dispose()
        shutil.rmtree(upload_directory)
        assert not upload_directory.exists()

        # Restore exactly as `scripts/restore.sh` does, against the same
        # database URL the script's `db` service psql call targets.
        staging = tmp_path / "restore"
        staging.mkdir()
        with tarfile.open(archive, "r:gz") as tar:
            assert set(tar.getnames()) == {"database.sql", "uploads.tar"}
            tar.extract("database.sql", staging, filter="data")
            tar.extract("uploads.tar", staging, filter="data")

        with (staging / "database.sql").open("rb") as dump:
            restored = subprocess.run(
                [
                    "psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    backup._pg_dump_url(settings.database_url),
                ],
                stdin=dump,
                capture_output=True,
                check=False,
            )
        assert restored.returncode == 0, restored.stderr.decode(errors="replace")

        upload_directory.mkdir(parents=True)
        with tarfile.open(staging / "uploads.tar") as uploads:
            uploads.extractall(upload_directory, filter="data")

        restore_engine = create_engine()
        restore_factory = async_sessionmaker(restore_engine, expire_on_commit=False)
        try:
            assert await _counts(restore_factory) == before
            assert _upload_files(upload_directory) == files_before

            async with restore_factory() as session:
                decision = await session.get(Decision, seed["decision_id"])
                assert decision is not None
                assert decision.statement == "Authentication was postponed."
                evidence = (
                    await session.execute(
                        text(
                            "SELECT quote FROM decision_evidence "
                            "WHERE decision_id = :decision_id"
                        ),
                        {"decision_id": seed["decision_id"]},
                    )
                ).scalar_one()
                assert evidence == _QUOTE
                conversation = await session.get(
                    Conversation, seed["conversation_id"]
                )
                assert conversation is not None
                assert conversation.title == "Auth"
        finally:
            async with restore_factory() as cleanup:
                await cleanup.execute(
                    delete(Workspace).where(Workspace.id == seed["workspace_id"])
                )
                await cleanup.commit()
            await restore_engine.dispose()
    finally:
        await engine.dispose()
