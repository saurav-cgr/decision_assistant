import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_only_one_document_version_is_active(
    db_session: AsyncSession,
) -> None:
    workspace_id = uuid4()
    document_id = uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
        {"id": workspace_id, "name": "Test workspace"},
    )
    await db_session.execute(
        text(
            "INSERT INTO documents (id, workspace_id, display_name, media_type) "
            "VALUES (:id, :workspace_id, :display_name, :media_type)"
        ),
        {
            "id": document_id,
            "workspace_id": workspace_id,
            "display_name": "meeting.md",
            "media_type": "text/markdown",
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO document_versions "
            "(id, document_id, version_number, state, checksum, storage_path, "
            "chunking_profile) "
            "VALUES (:id, :document_id, 1, 'active', :checksum, :storage_path, "
            ":chunking_profile)"
        ),
        {
            "id": uuid4(),
            "document_id": document_id,
            "checksum": "a" * 64,
            "storage_path": "uploads/meeting-v1.md",
            "chunking_profile": json.dumps(
                {
                    "algorithm": "structural-token-v1",
                    "encoding": "cl100k_base",
                    "target_tokens": 450,
                    "max_tokens": 600,
                    "overlap_tokens": 60,
                }
            ),
        },
    )

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO document_versions "
                "(id, document_id, version_number, state, checksum, storage_path) "
                "VALUES (:id, :document_id, 2, 'active', :checksum, :storage_path)"
            ),
            {
                "id": uuid4(),
                "document_id": document_id,
                "checksum": "b" * 64,
                "storage_path": "uploads/meeting-v2.md",
            },
        )


@pytest.mark.asyncio
async def test_passages_require_document_version(
    db_session: AsyncSession,
) -> None:
    result = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'passages' "
            "AND column_name = 'document_version_id'"
        )
    )

    assert result.scalar_one() == "NO"


@pytest.mark.asyncio
async def test_document_version_chunking_profile_is_required_and_explicit(
    db_session: AsyncSession,
) -> None:
    nullability = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'document_versions' "
            "AND column_name = 'chunking_profile'"
        )
    )
    assert nullability.scalar_one() == "NO"

    workspace_id = uuid4()
    document_id = uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
        {"id": workspace_id, "name": "Chunking workspace"},
    )
    await db_session.execute(
        text(
            "INSERT INTO documents (id, workspace_id, display_name, media_type) "
            "VALUES (:id, :workspace_id, :display_name, :media_type)"
        ),
        {
            "id": document_id,
            "workspace_id": workspace_id,
            "display_name": "meeting.md",
            "media_type": "text/markdown",
        },
    )
    version_id = uuid4()
    chunking_profile = {
        "algorithm": "structural-token-v1",
        "encoding": "cl100k_base",
        "target_tokens": 450,
        "max_tokens": 600,
        "overlap_tokens": 60,
    }
    await db_session.execute(
        text(
            "INSERT INTO document_versions "
            "(id, document_id, version_number, state, checksum, storage_path, "
            "chunking_profile) "
            "VALUES (:id, :document_id, 1, 'staging', :checksum, :storage_path, "
            ":chunking_profile)"
        ),
        {
            "id": version_id,
            "document_id": document_id,
            "checksum": "a" * 64,
            "storage_path": "uploads/meeting.md",
            "chunking_profile": json.dumps(chunking_profile),
        },
    )

    stored = await db_session.execute(
        text(
            "SELECT chunking_profile FROM document_versions "
            "WHERE id = :id"
        ),
        {"id": version_id},
    )
    assert stored.scalar_one() == chunking_profile


@pytest.mark.asyncio
async def test_passage_embedding_profile_is_required_no_legacy_state(
    db_session: AsyncSession,
) -> None:
    nullability = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'passages' "
            "AND column_name = 'embedding_profile'"
        )
    )
    assert nullability.scalar_one() == "NO"


@pytest.mark.asyncio
async def test_retrieval_and_evaluation_columns_round_trip(
    db_session: AsyncSession,
) -> None:
    workspace_id = uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
        {"id": workspace_id, "name": "Trace workspace"},
    )

    trace_id = uuid4()
    rerank = {
        "status": "completed",
        "input_passage_ids": [str(uuid4())],
        "output_passage_ids": [str(uuid4())],
        "profile": {"provider": "fake", "prompt_contract_version": "gemini-json-v2"},
        "fallback_reason": None,
    }
    selected_metadata = [
        {
            "passage_id": str(uuid4()),
            "document_version_id": str(uuid4()),
            "chunking_profile": {"algorithm": "structural-token-v1"},
            "source_kind": "markdown",
        }
    ]
    await db_session.execute(
        text(
            "INSERT INTO retrieval_traces "
            "(id, workspace_id, request_id, normalized_question, rerank, "
            "selected_passage_metadata) "
            "VALUES (:id, :workspace_id, :request_id, :question, :rerank, "
            ":metadata)"
        ),
        {
            "id": trace_id,
            "workspace_id": workspace_id,
            "request_id": "req-1",
            "question": "Why was authentication postponed?",
            "rerank": json.dumps(rerank),
            "metadata": json.dumps(selected_metadata),
        },
    )
    trace = await db_session.execute(
        text(
            "SELECT rerank, selected_passage_metadata FROM retrieval_traces "
            "WHERE id = :id"
        ),
        {"id": trace_id},
    )
    assert trace.one() == (rerank, selected_metadata)

    run_id = uuid4()
    snapshot = [
        {
            "document_version_id": str(uuid4()),
            "chunking_profile": {"algorithm": "structural-token-v1"},
            "source_kind": "markdown",
        }
    ]
    await db_session.execute(
        text(
            "INSERT INTO evaluation_runs "
            "(id, workspace_id, strategy, status, dataset_version, "
            "corpus_snapshot) "
            "VALUES (:id, :workspace_id, 'hybrid', 'pending', :version, "
            ":snapshot)"
        ),
        {
            "id": run_id,
            "workspace_id": workspace_id,
            "version": "decision-eval-v1",
            "snapshot": json.dumps(snapshot),
        },
    )
    run = await db_session.execute(
        text(
            "SELECT corpus_snapshot FROM evaluation_runs WHERE id = :id"
        ),
        {"id": run_id},
    )
    assert run.scalar_one() == snapshot


@pytest.mark.asyncio
async def test_question_answer_history_schema_enforces_cache_identity(
    db_session: AsyncSession,
) -> None:
    workspace_id = uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
        {"id": workspace_id, "name": "Question history workspace"},
    )
    revision = await db_session.scalar(
        text("SELECT knowledge_revision FROM workspaces WHERE id = :id"),
        {"id": workspace_id},
    )
    assert revision == 1

    trace_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO retrieval_traces "
            "(id, workspace_id, request_id, normalized_question) "
            "VALUES (:id, :workspace_id, :request_id, :question)"
        ),
        {
            "id": trace_id,
            "workspace_id": workspace_id,
            "request_id": "history-request",
            "question": "why was authentication postponed?",
        },
    )
    answer_id = uuid4()
    response = {
        "answer": "Authentication was postponed.",
        "state": "answered",
        "confidence": "high",
        "claims": [],
        "citations": [],
        "conflicts": [],
        "unsupported_facets": [],
        "trace_id": str(trace_id),
    }
    await db_session.execute(
        text(
            "INSERT INTO question_answers "
            "(id, workspace_id, trace_id, question, normalized_question, response, "
            "knowledge_revision) "
            "VALUES (:id, :workspace_id, :trace_id, :question, "
            ":normalized_question, :response, 1)"
        ),
        {
            "id": answer_id,
            "workspace_id": workspace_id,
            "trace_id": trace_id,
            "question": "Why was authentication postponed?",
            "normalized_question": "why was authentication postponed?",
            "response": json.dumps(response),
        },
    )

    stored = await db_session.execute(
        text(
            "SELECT response, response_schema_version, knowledge_revision "
            "FROM question_answers WHERE id = :id"
        ),
        {"id": answer_id},
    )
    assert stored.one() == (response, 1, 1)

    indexes = await db_session.scalars(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'question_answers'"
        )
    )
    assert "ix_question_answers_workspace_last_asked" in set(indexes)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO question_answers "
                "(id, workspace_id, trace_id, question, normalized_question, "
                "response, knowledge_revision) "
                "VALUES (:id, :workspace_id, :trace_id, :question, "
                ":normalized_question, :response, 1)"
            ),
            {
                "id": uuid4(),
                "workspace_id": workspace_id,
                "trace_id": trace_id,
                "question": "WHY was authentication postponed?",
                "normalized_question": "why was authentication postponed?",
                "response": json.dumps(response),
            },
        )


def test_migration_source_has_no_legacy_backfill_or_profile_path() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0001_initial.py"
    ).read_text(encoding="utf-8")

    assert "UPDATE workspaces" not in source
    assert "legacy-character-v1" not in source
    assert "reindex" not in source.lower()


@pytest.mark.asyncio
async def test_pgvector_and_search_indexes_are_available(
    db_session: AsyncSession,
) -> None:
    extension = await db_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    )
    assert extension.scalar_one() == "vector"

    search_column = await db_session.execute(
        text(
            "SELECT udt_name, is_generated, generation_expression "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'passages' "
            "AND column_name = 'search_vector'"
        )
    )
    udt_name, is_generated, expression = search_column.one()
    assert udt_name == "tsvector"
    assert is_generated == "ALWAYS"
    assert "english" in expression

    indexes = await db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'passages'"
        )
    )
    definitions = [definition.lower() for definition in indexes.scalars()]
    assert any("using gin" in definition and "search_vector" in definition for definition in definitions)
    assert any(
        ("using hnsw" in definition or "using ivfflat" in definition)
        and "embedding" in definition
        for definition in definitions
    )
