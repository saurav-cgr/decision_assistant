"""Schema contracts for answer history, conversations, migrations and indexes.

Split out of `test_schema.py` (corpus/ingestion and evaluation schema) so both files stay under
AGENTS.md's 500-line cap for hand-written files (DB53).
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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


@pytest.mark.asyncio
async def test_conversation_schema_enforces_workspace_scoping_and_turn_order(
    db_session: AsyncSession,
) -> None:
    workspace_id = uuid4()
    await db_session.execute(
        text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
        {"id": workspace_id, "name": "Conversation workspace"},
    )
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
            "request_id": "conversation-request",
            "question": "who changed authentication?",
        },
    )
    conversation_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO conversations (id, workspace_id, title) "
            "VALUES (:id, :workspace_id, :title)"
        ),
        {
            "id": conversation_id,
            "workspace_id": workspace_id,
            "title": "Who changed authentication?",
        },
    )
    response = {
        "answer": "The authentication owner changed.",
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
            "INSERT INTO conversation_messages "
            "(id, conversation_id, trace_id, turn_number, question, response, "
            "knowledge_revision) "
            "VALUES (:id, :conversation_id, :trace_id, 1, :question, :response, 1)"
        ),
        {
            "id": uuid4(),
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "question": "Who changed authentication?",
            "response": json.dumps(response),
        },
    )

    stored = await db_session.execute(
        text(
            "SELECT title, response_schema_version, knowledge_revision "
            "FROM conversations JOIN conversation_messages "
            "ON conversations.id = conversation_messages.conversation_id "
            "WHERE conversations.id = :id"
        ),
        {"id": conversation_id},
    )
    assert stored.one() == ("Who changed authentication?", 1, 1)

    indexes = await db_session.scalars(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = 'conversations'"
        )
    )
    assert "ix_conversations_workspace_updated" in set(indexes)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO conversation_messages "
                "(id, conversation_id, trace_id, turn_number, question, response, "
                "knowledge_revision) "
                "VALUES (:id, :conversation_id, :trace_id, 1, :question, :response, 1)"
            ),
            {
                "id": uuid4(),
                "conversation_id": conversation_id,
                "trace_id": trace_id,
                "question": "Why did this change?",
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
