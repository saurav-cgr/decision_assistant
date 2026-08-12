from typing import Any
from uuid import uuid4

import pytest

from decision_assistant.evaluation import service as evaluation_service_module
from decision_assistant.evaluation.service import SemanticRetrievalService
from decision_assistant.providers.base import EmbeddingPurpose
from decision_assistant.providers.fakes import FakeEmbeddingProvider
from decision_assistant.retrieval.schemas import RetrievalSearchRequest
from decision_assistant.retrieval import service as retrieval_service_module
from decision_assistant.retrieval.service import HybridRetrievalService


class EmptyRepository:
    async def semantic_search(self, *_: Any, **__: Any) -> list[Any]:
        return []

    async def keyword_search(self, *_: Any, **__: Any) -> list[Any]:
        return []

    async def decision_search(self, *_: Any, **__: Any) -> list[Any]:
        return []


class RecordingSession:
    def add(self, value: Any) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid4()

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "service_type", [HybridRetrievalService, SemanticRetrievalService]
)
async def test_runtime_and_semantic_evaluation_retrieval_embed_queries(
    service_type: type[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def current_profile(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(
        retrieval_service_module,
        "require_current_embedding_profile",
        current_profile,
    )
    monkeypatch.setattr(
        evaluation_service_module,
        "require_current_embedding_profile",
        current_profile,
    )
    provider = FakeEmbeddingProvider(dimension=768)
    arguments: dict[str, Any] = {
        "session": RecordingSession(),
        "embedding_provider": provider,
    }
    if service_type is SemanticRetrievalService:
        arguments["top_k"] = 5
    service = service_type(**arguments)
    service._repository = EmptyRepository()

    await service.search(
        RetrievalSearchRequest(question="Authentication"),
        request_id="purpose-contract",
    )

    assert provider.purposes == [EmbeddingPurpose.QUERY]
