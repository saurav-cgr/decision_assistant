from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from decision_assistant.config import Settings
from decision_assistant.db import create_engine, create_session_factory
from decision_assistant.models import Workspace
from decision_assistant.providers.factory import create_embedding_provider_handle
from decision_assistant.workspace.embedding_migration import EmbeddingMigrationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomically reindex active passage embeddings",
    )
    parser.add_argument("--workspace-id", type=UUID)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser


async def reindex_embeddings(
    *,
    settings: Settings,
    workspace_id: UUID | None,
    batch_size: int,
) -> dict[str, object]:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    provider_handle = None
    try:
        provider_handle = create_embedding_provider_handle(settings)
        async with sessions() as session:
            try:
                resolved_workspace_id = workspace_id
                if resolved_workspace_id is None:
                    resolved_workspace_id = await session.scalar(
                        select(Workspace.id).order_by(Workspace.created_at).limit(1)
                    )
                if resolved_workspace_id is None:
                    raise ValueError("Workspace not found")
                result = await EmbeddingMigrationService(
                    session=session,
                    embedding_provider=provider_handle.embedding,
                    batch_size=batch_size,
                ).run(resolved_workspace_id)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return {
            "workspace_id": str(result.workspace_id),
            "passage_count": result.passage_count,
            "embedding_profile": result.embedding_profile,
        }
    finally:
        try:
            if provider_handle is not None:
                await provider_handle.aclose()
        finally:
            await engine.dispose()


def main() -> None:
    arguments = _parser().parse_args()
    result = asyncio.run(
        reindex_embeddings(
            settings=Settings(),
            workspace_id=arguments.workspace_id,
            batch_size=arguments.batch_size,
        )
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
