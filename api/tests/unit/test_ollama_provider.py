import json

import httpx
import pytest
from pydantic import BaseModel

from decision_assistant.providers.base import (
    EmbeddingPurpose,
    GenerationRequest,
    ProviderOutputInvalid,
)
from decision_assistant.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaGenerationProvider,
)


class AnswerStub(BaseModel):
    answer: str


def request(
    user: str = "Use evidence only",
    system: str = "trusted policy",
) -> GenerationRequest:
    return GenerationRequest(system_instruction=system, user_content=user)


@pytest.mark.asyncio
async def test_embedding_adapter_sends_batch_and_validates_dimension() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    provider = OllamaEmbeddingProvider(
        base_url="http://ollama.test",
        model="embedding-test",
        dimension=3,
        retry_count=0,
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed(
        ["evidence"], purpose=EmbeddingPurpose.DOCUMENT
    ) == [[0.1, 0.2, 0.3]]
    assert requests == [{"model": "embedding-test", "input": ["evidence"]}]


@pytest.mark.asyncio
async def test_generation_adapter_requests_schema_and_zero_temperature() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": '{"answer":"supported"}'}},
        )

    provider = OllamaGenerationProvider(
        base_url="http://ollama.test",
        model="generation-test",
        retry_count=0,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.generate(request(), AnswerStub)

    assert result == AnswerStub(answer="supported")
    assert provider.profile.prompt_contract_version == "ollama-json-v3"
    assert requests[0]["format"] == AnswerStub.model_json_schema()
    assert requests[0]["options"] == {"temperature": 0}
    assert requests[0]["stream"] is False
    assert requests[0]["messages"] == [
        {"role": "system", "content": "trusted policy"},
        {"role": "user", "content": "Use evidence only"},
    ]


@pytest.mark.asyncio
async def test_generation_adapter_maps_local_json_validation_to_output_invalid() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not json"}})

    provider = OllamaGenerationProvider(
        base_url="http://ollama.test",
        model="generation-test",
        retry_count=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderOutputInvalid):
        await provider.generate(request(), AnswerStub)


@pytest.mark.asyncio
async def test_adapter_retries_transient_status_only() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "loading"})
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})

    provider = OllamaEmbeddingProvider(
        base_url="http://ollama.test",
        model="embedding-test",
        dimension=2,
        retry_count=1,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed(
        ["retry"], purpose=EmbeddingPurpose.QUERY
    ) == [[1.0, 0.0]]
    assert attempts == 2
