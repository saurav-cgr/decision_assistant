import asyncio
import math
from typing import Any

import httpx
from pydantic import ValidationError

from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingPurpose,
    GenerationProfile,
    GenerationRequest,
    ProviderOutputInvalid,
    ProviderInputTooLarge,
    ProviderResponseInvalid,
    ProviderUnavailable,
    ResponseModelT,
)

TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class _OllamaAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        retry_count: int,
        timeout_seconds: float,
        retry_backoff_seconds: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        if retry_count < 0:
            raise ValueError("Retry count cannot be negative")
        self._base_url = base_url.rstrip("/")
        self._retry_count = retry_count
        self._timeout_seconds = timeout_seconds
        self._retry_backoff_seconds = retry_backoff_seconds
        self._transport = transport

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._retry_count + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = await client.post(path, json=payload)
            except httpx.RequestError as exc:
                if attempt < self._retry_count:
                    await self._wait_before_retry(attempt)
                    continue
                raise ProviderUnavailable() from exc

            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt < self._retry_count:
                    await self._wait_before_retry(attempt)
                    continue
                raise ProviderUnavailable(
                    f"Ollama unavailable after HTTP {response.status_code}"
                )

            if response.is_error:
                raise ProviderResponseInvalid(
                    f"Ollama rejected request with HTTP {response.status_code}"
                )

            try:
                result = response.json()
            except ValueError as exc:
                raise ProviderResponseInvalid("Ollama returned non-JSON data") from exc
            if not isinstance(result, dict):
                raise ProviderResponseInvalid("Ollama returned invalid JSON shape")
            return result

        raise ProviderUnavailable()

    async def _wait_before_retry(self, attempt: int) -> None:
        delay = self._retry_backoff_seconds * (2**attempt)
        if delay > 0:
            await asyncio.sleep(delay)


class OllamaEmbeddingProvider(_OllamaAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimension: int,
        retry_count: int = 2,
        timeout_seconds: float = 120.0,
        retry_backoff_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if dimension < 1:
            raise ValueError("Embedding dimension must be positive")
        super().__init__(
            base_url=base_url,
            retry_count=retry_count,
            timeout_seconds=timeout_seconds,
            retry_backoff_seconds=retry_backoff_seconds,
            transport=transport,
        )
        self._profile = EmbeddingProfile(
            provider="ollama",
            model=model,
            dimension=dimension,
            adapter_config_version="ollama-native-v1",
        )

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        if not texts:
            raise ValueError("Embedding input must contain at least one text")

        result = await self._post(
            "/api/embed",
            {"model": self.profile.model, "input": texts},
        )
        embeddings = result.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ProviderResponseInvalid("Ollama returned wrong embedding count")

        validated: list[list[float]] = []
        for vector in embeddings:
            if not isinstance(vector, list) or len(vector) != self.profile.dimension:
                raise ProviderResponseInvalid("Ollama returned wrong embedding dimension")
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in vector
            ):
                raise ProviderResponseInvalid("Ollama returned non-numeric embedding")
            validated.append([float(value) for value in vector])
        return validated


class OllamaGenerationProvider(_OllamaAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        retry_count: int = 2,
        timeout_seconds: float = 120.0,
        retry_backoff_seconds: float = 0.25,
        max_prompt_characters: int = 100_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            retry_count=retry_count,
            timeout_seconds=timeout_seconds,
            retry_backoff_seconds=retry_backoff_seconds,
            transport=transport,
        )
        self._model = model
        self._max_prompt_characters = max_prompt_characters
        self._profile = GenerationProfile(
            provider="ollama",
            model=model,
            api_version="/api/chat",
            sdk_version="httpx-0.28.1",
            temperature=0,
            schema_mode="json_schema",
            prompt_contract_version="ollama-json-v3",
        )

    @property
    def profile(self) -> GenerationProfile:
        return self._profile

    @property
    def max_prompt_characters(self) -> int:
        return self._max_prompt_characters

    async def generate(
        self,
        request: GenerationRequest,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        if request.total_characters > self.max_prompt_characters:
            raise ProviderInputTooLarge()
        result = await self._post(
            "/api/chat",
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": request.system_instruction},
                    {"role": "user", "content": request.user_content},
                ],
                "stream": False,
                "think": False,
                "format": response_model.model_json_schema(),
                "options": {"temperature": 0},
            },
        )
        try:
            message = result["message"]
            if not isinstance(message, dict):
                raise TypeError
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError
            return response_model.model_validate_json(content)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ProviderOutputInvalid() from None
