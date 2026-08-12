from collections.abc import Iterable, Mapping
from hashlib import sha256
from math import sqrt
from typing import Any

from pydantic import BaseModel, ValidationError

from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingPurpose,
    GenerationProfile,
    ProviderOutputInvalid,
    ProviderInputTooLarge,
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
            adapter_config_version="deterministic-v1",
        )
        self._next_error: Exception | None = None
        self.purposes: list[EmbeddingPurpose] = []

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    def fail_next(self, error: Exception | None = None) -> None:
        self._next_error = error or ProviderUnavailable()

    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        if not texts:
            raise ValueError("Embedding input must contain at least one text")
        self.purposes.append(purpose)
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
    def __init__(
        self,
        responses: Iterable[QueuedResponse] = (),
        *,
        max_prompt_characters: int = 100_000,
    ) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []
        self._profile = GenerationProfile(
            provider="fake",
            model="queued-response",
            api_version="test",
            sdk_version="test",
            temperature=0,
            schema_mode="json_schema",
            prompt_contract_version="fake-v1",
        )
        self._max_prompt_characters = max_prompt_characters

    @property
    def profile(self) -> GenerationProfile:
        return self._profile

    @property
    def max_prompt_characters(self) -> int:
        return self._max_prompt_characters

    def queue(self, response: QueuedResponse) -> None:
        self._responses.append(response)

    def fail_next(self, error: Exception | None = None) -> None:
        self._responses.insert(0, error or ProviderUnavailable())

    async def generate(
        self,
        prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        if len(prompt) > self.max_prompt_characters:
            raise ProviderInputTooLarge()
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("No fake generation response queued")

        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        try:
            return response_model.model_validate(response)
        except ValidationError:
            raise ProviderOutputInvalid() from None
