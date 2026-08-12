import pytest
from pydantic import BaseModel

from decision_assistant.providers.base import EmbeddingPurpose, ProviderOutputInvalid
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)


class AnswerStub(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_fake_embedding_is_deterministic() -> None:
    provider = FakeEmbeddingProvider(dimension=4)

    assert await provider.embed(
        ["same"], purpose=EmbeddingPurpose.DOCUMENT
    ) == await provider.embed(["same"], purpose=EmbeddingPurpose.DOCUMENT)


@pytest.mark.asyncio
async def test_fake_embedding_rejects_empty_application_batch() -> None:
    provider = FakeEmbeddingProvider(dimension=4)

    with pytest.raises(ValueError, match="at least one"):
        await provider.embed([], purpose=EmbeddingPurpose.DOCUMENT)


@pytest.mark.asyncio
async def test_fake_generation_validates_response_model() -> None:
    provider = FakeGenerationProvider([{"answer": "supported"}])

    result = await provider.generate("prompt", AnswerStub)

    assert result.answer == "supported"


@pytest.mark.asyncio
async def test_fake_generation_maps_queued_validation_failure_to_output_invalid() -> None:
    provider = FakeGenerationProvider([{"wrong": "shape"}])

    with pytest.raises(ProviderOutputInvalid):
        await provider.generate("prompt", AnswerStub)
