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
            "(id, document_id, version_number, state, checksum, storage_path) "
            "VALUES (:id, :document_id, 1, 'active', :checksum, :storage_path)"
        ),
        {
            "id": uuid4(),
            "document_id": document_id,
            "checksum": "a" * 64,
            "storage_path": "uploads/meeting-v1.md",
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
