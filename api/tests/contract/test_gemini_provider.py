import math
import os
from collections.abc import Awaitable
from typing import Any, TypeVar

import pytest
import pytest_asyncio
from pydantic import BaseModel

from decision_assistant.config import get_settings
from decision_assistant.providers.base import EmbeddingPurpose, ProviderError
from decision_assistant.providers.factory import create_provider_bundle

pytestmark = [
    pytest.mark.live_provider,
    pytest.mark.skipif(
        os.getenv("GEMINI_CONTRACT_TESTS") != "1",
        reason="Set GEMINI_CONTRACT_TESTS=1 to call configured Gemini models",
    ),
]


class ContractAnswer(BaseModel):
    answer: str


ResultT = TypeVar("ResultT")


@pytest_asyncio.fixture
async def gemini_bundle() -> Any:
    settings = get_settings().model_copy(
        update={
            "generation_provider": "gemini",
            "embedding_provider": "gemini",
        }
    )
    api_key = getattr(settings, "gemini_api_key", None)
    raw_key = (
        api_key.get_secret_value()
        if hasattr(api_key, "get_secret_value")
        else api_key
    )
    if not raw_key:
        pytest.skip("Gemini API key is not configured; live contract is inconclusive")

    assert settings.generation_provider == "gemini"
    assert settings.embedding_provider == "gemini"
    bundle = create_provider_bundle(settings)
    assert bundle.generation.profile.provider == "gemini"
    assert bundle.embedding.profile.provider == "gemini"
    try:
        yield bundle
    finally:
        await bundle.aclose()


async def run_live_provider(operation: Awaitable[ResultT]) -> ResultT:
    try:
        return await operation
    except ProviderError as error:
        if error.code == "provider_quota_exhausted":
            pytest.skip("Gemini quota exhausted; live contract is inconclusive")
        raise


@pytest.mark.asyncio
async def test_configured_embedding_model_returns_768_finite_values(
    gemini_bundle: Any,
) -> None:
    embeddings = await run_live_provider(
        gemini_bundle.embedding.embed(
            ["What was decided about authentication?"],
            purpose=EmbeddingPurpose.QUERY,
        )
    )

    assert len(embeddings) == 1
    assert len(embeddings[0]) == 768
    assert all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in embeddings[0]
    )


@pytest.mark.asyncio
async def test_configured_generation_model_returns_requested_schema(
    gemini_bundle: Any,
) -> None:
    result = await run_live_provider(
        gemini_bundle.generation.generate(
            "Return JSON with answer set to the single word supported.",
            ContractAnswer,
        )
    )

    assert result == ContractAnswer(answer="supported")
