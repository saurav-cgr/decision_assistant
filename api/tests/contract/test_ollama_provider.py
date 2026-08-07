import os

import pytest
from pydantic import BaseModel

from decision_assistant.config import get_settings
from decision_assistant.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaGenerationProvider,
)

pytestmark = pytest.mark.skipif(
    os.getenv("OLLAMA_CONTRACT_TESTS") != "1",
    reason="Set OLLAMA_CONTRACT_TESTS=1 to use local Ollama models",
)


class ContractAnswer(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_configured_embedding_model_returns_expected_dimension() -> None:
    settings = get_settings()
    provider = OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
        dimension=settings.ollama_embedding_dimension,
        timeout_seconds=settings.model_timeout_seconds,
        retry_count=settings.model_retry_count,
    )

    embeddings = await provider.embed(["authentication decision"])

    assert len(embeddings) == 1
    assert len(embeddings[0]) == settings.ollama_embedding_dimension


@pytest.mark.asyncio
async def test_configured_generation_model_returns_schema() -> None:
    settings = get_settings()
    provider = OllamaGenerationProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_generation_model,
        timeout_seconds=settings.model_timeout_seconds,
        retry_count=settings.model_retry_count,
    )

    result = await provider.generate(
        "Return JSON with answer set to the single word supported.",
        ContractAnswer,
    )

    assert result.answer == "supported"
