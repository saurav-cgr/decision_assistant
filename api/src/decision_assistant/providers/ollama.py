import asyncio
from typing import Any

import httpx
from pydantic import ValidationError

from decision_assistant.providers.base import (
    EmbeddingProfile,
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
        )

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

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
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in vector):
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

    async def generate(
        self,
        prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        result = await self._post(
            "/api/chat",
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
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
            raise ProviderResponseInvalid() from exc
