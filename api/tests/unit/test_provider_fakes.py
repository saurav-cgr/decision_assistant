import pytest
from pydantic import BaseModel

from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)


class AnswerStub(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_fake_embedding_is_deterministic() -> None:
    provider = FakeEmbeddingProvider(dimension=4)

    assert await provider.embed(["same"]) == await provider.embed(["same"])


@pytest.mark.asyncio
async def test_fake_generation_validates_response_model() -> None:
    provider = FakeGenerationProvider([{"answer": "supported"}])

    result = await provider.generate("prompt", AnswerStub)

    assert result.answer == "supported"
