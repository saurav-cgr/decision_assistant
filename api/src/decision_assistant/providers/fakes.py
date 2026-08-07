from collections.abc import Iterable, Mapping
from hashlib import sha256
from math import sqrt
from typing import Any

from pydantic import BaseModel

from decision_assistant.providers.base import (
    EmbeddingProfile,
    ProviderUnavailable,
    ResponseModelT,
)

QueuedResponse = Mapping[str, Any] | BaseModel | Exception


class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 8) -> None:
        if dimension < 1:
            raise ValueError("Embedding dimension must be positive")
        self._profile = EmbeddingProfile(
            provider="fake",
            model="deterministic-sha256",
            dimension=dimension,
        )
        self._next_error: Exception | None = None

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    def fail_next(self, error: Exception | None = None) -> None:
        self._next_error = error or ProviderUnavailable()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._next_error is not None:
            error, self._next_error = self._next_error, None
            raise error
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.profile.dimension:
            digest = sha256(f"{counter}:{text}".encode()).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            counter += 1

        vector = values[: self.profile.dimension]
        magnitude = sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]


class FakeGenerationProvider:
    def __init__(self, responses: Iterable[QueuedResponse] = ()) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def queue(self, response: QueuedResponse) -> None:
        self._responses.append(response)

    def fail_next(self, error: Exception | None = None) -> None:
        self._responses.insert(0, error or ProviderUnavailable())

    async def generate(
        self,
        prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("No fake generation response queued")

        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response_model.model_validate(response)
