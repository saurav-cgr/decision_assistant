"""Fakes for the Gemini provider tests (DB53).

The stub SDK surface and the provider builders live here so `test_gemini_provider.py` (embedding
half) and `test_gemini_generation.py` (generation half) share one definition instead of each
re-declaring it. Extracted for AGENTS.md's 500-line cap on hand-written files; DB30 and DB49 set the
same precedent (`tests/support/`).
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from decision_assistant.providers.base import GenerationRequest, ProviderError
from decision_assistant.providers.gemini import (
    GeminiEmbeddingProvider,
    GeminiGenerationProvider,
)

EMBEDDING_MODEL = "gemini-embedding-2"
GENERATION_MODEL = "gemini-3.1-flash-lite"
DIMENSION = 768


class AnswerStub(BaseModel):
    answer: str


@dataclass
class SdkError(Exception):
    status_code: int | None = None
    retry_after: float | None = None
    reason: str | None = None

    def __str__(self) -> str:
        return self.reason or f"SDK error {self.status_code}"


class RecordingModels:
    def __init__(self) -> None:
        self.embedding_calls: list[dict[str, Any]] = []
        self.generation_calls: list[dict[str, Any]] = []
        self.embedding_results: list[Any] = []
        self.generation_results: list[Any] = []

    async def embed_content(self, **kwargs: Any) -> Any:
        self.embedding_calls.append(kwargs)
        result = self.embedding_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def generate_content(self, **kwargs: Any) -> Any:
        self.generation_calls.append(kwargs)
        result = self.generation_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def sdk_client(models: RecordingModels) -> Any:
    return SimpleNamespace(aio=SimpleNamespace(models=models))


def embedding_response(vectors: list[list[float]]) -> Any:
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=vector) for vector in vectors]
    )


def generation_response(text: str) -> Any:
    return SimpleNamespace(text=text)


def embedding_provider(models: RecordingModels, **overrides: Any) -> Any:
    arguments = {
        "client": sdk_client(models),
        "model": EMBEDDING_MODEL,
        "dimension": DIMENSION,
        "adapter_config_version": "retrieval-prefix-v1",
        "batch_size": 32,
        "retry_count": 2,
        "retry_backoff_seconds": 0,
    }
    arguments.update(overrides)
    return GeminiEmbeddingProvider(**arguments)


def generation_provider(models: RecordingModels, **overrides: Any) -> Any:
    arguments = {
        "client": sdk_client(models),
        "model": GENERATION_MODEL,
        "prompt_version": "gemini-json-v2",
        "max_prompt_characters": 100_000,
        "retry_count": 2,
        "retry_backoff_seconds": 0,
    }
    arguments.update(overrides)
    return GeminiGenerationProvider(**arguments)


def request(
    user: str = "prompt",
    system: str = "trusted policy",
) -> GenerationRequest:
    return GenerationRequest(system_instruction=system, user_content=user)


def config_payload(config: Any) -> dict[str, Any]:
    if hasattr(config, "model_dump"):
        return config.model_dump(exclude_none=True)
    if isinstance(config, dict):
        return {key: value for key, value in config.items() if value is not None}
    return {
        key: value
        for key, value in vars(config).items()
        if not key.startswith("_") and value is not None
    }


def error_code(error: pytest.ExceptionInfo[ProviderError]) -> str:
    return error.value.code
