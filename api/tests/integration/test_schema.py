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
async def test_passage_structural_metadata_is_required_with_empty_default(
    db_session: AsyncSession,
) -> None:
    column_default = await db_session.execute(
        text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'passages' "
            "AND column_name = 'structural_metadata'"
        )
    )
    assert column_default.scalar_one() == "'{}'::jsonb"

    nullability = await db_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'passages' "
            "AND column_name = 'structural_metadata'"
        )
    )
    assert nullability.scalar_one() == "NO"


@pytest.mark.asyncio
async def test_retrieval_unit_hierarchy_schema_contract(
    db_session: AsyncSession,
) -> None:
    columns = await db_session.execute(
        text(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'passages' "
            "AND column_name IN ('retrieval_unit_kind', 'parent_passage_id') "
            "ORDER BY column_name"
        )
    )
    assert columns.all() == [
        ("parent_passage_id", "YES", None),
        ("retrieval_unit_kind", "NO", "'passage'::character varying"),
    ]

    constraints = await db_session.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'passages'::regclass "
            "AND conname IN ("
            "'ck_passages_retrieval_unit_kind', "
            "'ck_passages_parent_unit_link', "
            "'fk_passages_parent_passage_id') "
            "ORDER BY conname"
        )
    )
    assert [name for (name,) in constraints] == [
        "ck_passages_parent_unit_link",
        "ck_passages_retrieval_unit_kind",
        "fk_passages_parent_passage_id",
    ]


@pytest.mark.asyncio
async def test_evaluation_schema_allows_retrieval_unit_strategies(
    db_session: AsyncSession,
) -> None:
    constraint = await db_session.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'evaluation_runs'::regclass "
            "AND conname = 'ck_evaluation_runs_strategy'"
        )
    )
    definition = constraint.scalar_one()
    assert "sentence_expanded" in definition
    assert "parent_child_merged" in definition


@pytest.mark.asyncio
async def test_passage_embedding_profile_is_nullable_for_cache_backed_rows(
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
    assert nullability.scalar_one() == "YES"


@pytest.mark.asyncio
async def test_embedding_cache_schema_contract(db_session: AsyncSession) -> None:
    columns = await db_session.execute(
        text(
            "SELECT column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'embedding_cache' "
            "AND column_name IN ("
            "'workspace_id', 'content_hash', 'embedding_profile_fingerprint', "
            "'embedding_profile', 'embedding') ORDER BY column_name"
        )
    )
    assert columns.all() == [
        ("content_hash", "NO"),
        ("embedding", "NO"),
        ("embedding_profile", "NO"),
        ("embedding_profile_fingerprint", "NO"),
        ("workspace_id", "NO"),
    ]

    constraints = await db_session.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'embedding_cache'::regclass "
            "AND conname IN ("
            "'uq_embedding_cache_content_profile', "
            "'embedding_cache_workspace_id_fkey') ORDER BY conname"
        )
    )
    assert [name for (name,) in constraints] == [
        "embedding_cache_workspace_id_fkey",
        "uq_embedding_cache_content_profile",
    ]

    passage_fk = await db_session.execute(
        text(
            "SELECT confdeltype FROM pg_constraint "
            "WHERE conname = 'fk_passages_embedding_cache_id'"
        )
    )
    assert passage_fk.scalar_one().decode() == "n"

    index = await db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "AND indexname = 'ix_embedding_cache_embedding_hnsw'"
        )
    )
    assert "USING hnsw" in index.scalar_one()


@pytest.mark.asyncio
async def test_passage_embedding_columns_are_deprecated_and_nullable(
    db_session: AsyncSession,
) -> None:
    result = await db_session.execute(
        text(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'passages' "
            "AND column_name IN ('embedding', 'embedding_profile') "
            "ORDER BY column_name"
        )
    )
    assert result.all() == [
        ("embedding", "YES"),
        ("embedding_profile", "YES"),
    ]


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
