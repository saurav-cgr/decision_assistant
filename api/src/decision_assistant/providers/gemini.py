import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from random import random
from time import monotonic
from typing import Any

from pydantic import PydanticUserError, ValidationError

from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingPurpose,
    GenerationProfile,
    GenerationRequest,
    ProviderAuthenticationFailed,
    ProviderConfigurationInvalid,
    ProviderError,
    ProviderInputTooLarge,
    ProviderOutputInvalid,
    ProviderQuotaExhausted,
    ProviderRateLimited,
    ProviderResponseInvalid,
    ProviderSchemaUnsupported,
    ProviderUnavailable,
    ResponseModelT,
)

GEMINI_SDK_VERSION = "2.13.0"
GEMINI_API_VERSION = "v1beta"
FIXED_EMBEDDING_DIMENSION = 768
MAX_EMBEDDING_BATCH_SIZE = 32


class _GeminiAdapter:
    def __init__(
        self,
        *,
        client: Any,
        retry_count: int,
        retry_backoff_seconds: float,
        request_timeout_seconds: float,
        random_source: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        if retry_count < 0:
            raise ProviderConfigurationInvalid()
        self._client = client
        self._retry_count = retry_count
        self._retry_backoff_seconds = retry_backoff_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._random_source = random_source
        self._sleep = sleep

    async def _request(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        started = monotonic()
        for attempt in range(self._retry_count + 1):
            remaining = self._request_timeout_seconds - (monotonic() - started)
            if remaining <= 0:
                raise ProviderUnavailable() from None
            try:
                return await asyncio.wait_for(operation(), timeout=remaining)
            except ProviderError:
                raise
            except Exception as exc:
                mapped = _map_sdk_error(exc)
                if mapped.retryable and attempt < self._retry_count:
                    delay = _retry_delay(
                        exc,
                        self._retry_backoff_seconds,
                        attempt,
                        self._random_source,
                    )
                    if monotonic() - started + delay >= self._request_timeout_seconds:
                        if isinstance(mapped, ProviderRateLimited):
                            mapped = ProviderRateLimited(retryable=False)
                        raise mapped from None
                    if delay > 0:
                        await self._sleep(delay)
                    continue
                raise mapped from None
        raise ProviderUnavailable()


class GeminiEmbeddingProvider(_GeminiAdapter):
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        dimension: int,
        adapter_config_version: str,
        batch_size: int,
        max_input_characters: int = 100_000,
        retry_count: int = 2,
        retry_backoff_seconds: float = 0.25,
        request_timeout_seconds: float = 120.0,
        random_source: Callable[[], float] = random,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if dimension != FIXED_EMBEDDING_DIMENSION:
            raise ProviderConfigurationInvalid()
        if batch_size < 1 or batch_size > MAX_EMBEDDING_BATCH_SIZE:
            raise ProviderConfigurationInvalid()
        if adapter_config_version != "retrieval-prefix-v1":
            raise ProviderConfigurationInvalid()
        super().__init__(
            client=client,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff_seconds,
            request_timeout_seconds=request_timeout_seconds,
            random_source=random_source,
            sleep=sleep,
        )
        self._profile = EmbeddingProfile(
            provider="gemini",
            model=model,
            dimension=dimension,
            adapter_config_version=adapter_config_version,
        )
        self._batch_size = batch_size
        self._max_input_characters = max_input_characters

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
        if any(len(text) > self._max_input_characters for text in texts):
            raise ProviderInputTooLarge()

        formatted = [
            _embedding_content(_format_embedding_input(text, purpose))
            for text in texts
        ]
        vectors: list[list[float]] = []
        for start in range(0, len(formatted), self._batch_size):
            batch = formatted[start : start + self._batch_size]
            response = await self._request(
                lambda batch=batch: self._client.aio.models.embed_content(
                    model=self.profile.model,
                    contents=batch,
                    config={"output_dimensionality": self.profile.dimension},
                )
            )
            vectors.extend(_validate_embeddings(response, len(batch), self.profile.dimension))
        return vectors


class GeminiGenerationProvider(_GeminiAdapter):
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        prompt_version: str,
        max_prompt_characters: int,
        retry_count: int = 2,
        retry_backoff_seconds: float = 0.25,
        request_timeout_seconds: float = 120.0,
        random_source: Callable[[], float] = random,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(
            client=client,
            retry_count=retry_count,
            retry_backoff_seconds=retry_backoff_seconds,
            request_timeout_seconds=request_timeout_seconds,
            random_source=random_source,
            sleep=sleep,
        )
        self._profile = GenerationProfile(
            provider="gemini",
            model=model,
            api_version=GEMINI_API_VERSION,
            sdk_version=GEMINI_SDK_VERSION,
            temperature=0,
            schema_mode="json_schema",
            prompt_contract_version=prompt_version,
        )
        self._max_prompt_characters = max_prompt_characters

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
        if request.total_characters > self._max_prompt_characters:
            raise ProviderInputTooLarge()
        response = await self._request(
            lambda: self._client.aio.models.generate_content(
                model=self.profile.model,
                contents=request.user_content,
                config={
                    "temperature": self.profile.temperature,
                    "system_instruction": request.system_instruction,
                    "response_mime_type": "application/json",
                    "response_json_schema": response_model.model_json_schema(),
                },
            )
        )
        try:
            text = response.text
            if not isinstance(text, str):
                raise TypeError
            return response_model.model_validate_json(text)
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise ProviderOutputInvalid() from None


def _format_embedding_input(text: str, purpose: EmbeddingPurpose) -> str:
    if purpose is EmbeddingPurpose.DOCUMENT:
        return f"title: none | text: {text}"
    if purpose is EmbeddingPurpose.QUERY:
        return f"task: search result | query: {text}"
    raise ValueError("Unsupported embedding purpose")


def _embedding_content(text: str) -> dict[str, object]:
    # google-genai groups a list[str] into one multi-part Content. Explicit
    # Content objects preserve one input -> one embedding cardinality.
    return {"role": "user", "parts": [{"text": text}]}


def _validate_embeddings(
    response: Any,
    expected_count: int,
    dimension: int,
) -> list[list[float]]:
    embeddings = getattr(response, "embeddings", None)
    if not isinstance(embeddings, list) or len(embeddings) != expected_count:
        raise ProviderResponseInvalid()
    validated: list[list[float]] = []
    for item in embeddings:
        values = getattr(item, "values", None)
        if not isinstance(values, list) or len(values) != dimension:
            raise ProviderResponseInvalid()
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in values
        ):
            raise ProviderResponseInvalid()
        validated.append([float(value) for value in values])
    return validated


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if value is None:
        value = getattr(exc, "code", None)
    return value if isinstance(value, int) else None


def _retry_after(exc: Exception) -> float | None:
    value = getattr(exc, "retry_after", None)
    if value is None:
        details = getattr(exc, "details", None)
        if isinstance(details, dict):
            error = details.get("error", details)
            entries = error.get("details", []) if isinstance(error, dict) else []
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict) or "RetryInfo" not in str(
                    entry.get("@type", "")
                ):
                    continue
                value = entry.get("retryDelay") or entry.get("retry_delay")
                break
    if value is None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is not None:
            value = headers.get("retry-after")
    if isinstance(value, str):
        if value.endswith("s"):
            value = value[:-1]
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        seconds = value.get("seconds", 0)
        nanos = value.get("nanos", 0)
        if isinstance(seconds, (int, float)) and isinstance(nanos, (int, float)):
            value = float(seconds) + (float(nanos) / 1_000_000_000)
    return float(value) if isinstance(value, (int, float)) else None


def _retry_delay(
    exc: Exception,
    backoff: float,
    attempt: int,
    random_source: Callable[[], float],
) -> float:
    retry_after = _retry_after(exc)
    if retry_after is not None:
        return max(0.0, retry_after)
    jitter_sample = min(1.0, max(0.0, random_source()))
    jitter_factor = 0.8 + (0.4 * jitter_sample)
    return max(0.0, backoff * (2**attempt) * jitter_factor)


def _map_sdk_error(exc: Exception) -> ProviderError:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return ProviderUnavailable()
    status = _status_code(exc)
    details = getattr(exc, "details", None)
    classification = " ".join(
        str(value)
        for value in (
            getattr(exc, "reason", ""),
            getattr(exc, "status", ""),
            getattr(exc, "message", ""),
            json.dumps(details, sort_keys=True) if isinstance(details, dict) else "",
            str(exc),
        )
    ).lower()
    if isinstance(exc, (ValidationError, PydanticUserError, ValueError, TypeError)):
        if "schema" in classification:
            return ProviderSchemaUnsupported()
        return ProviderResponseInvalid()
    if exc.__class__.__name__ in {
        "UnknownApiResponseError",
        "UnknownFunctionCallArgumentError",
        "UnsupportedFunctionError",
    }:
        return ProviderResponseInvalid()
    if status in {401, 403}:
        return ProviderAuthenticationFailed()
    if status == 400 and any(
        marker in classification
        for marker in ("api key", "credential", "authentication")
    ):
        return ProviderAuthenticationFailed()
    if status == 429:
        if _is_hard_quota(details) or any(
            marker in classification
            for marker in (
                "daily quota",
                "per-day",
                "per day",
                "billing quota",
                "billing account disabled",
                "billing disabled",
                "hard project quota",
                "project quota exhausted",
                "project quota has been exhausted",
            )
        ):
            return ProviderQuotaExhausted()
        retry_after = _retry_after(exc)
        return ProviderRateLimited(
            retryable=retry_after is not None and 0 <= retry_after <= 60
        )
    if status in {408, 500, 502, 503, 504}:
        return ProviderUnavailable()
    if status == 400 and "schema" in classification:
        return ProviderSchemaUnsupported()
    if status is not None and 400 <= status < 500:
        return ProviderResponseInvalid()
    return ProviderUnavailable()


def _is_hard_quota(details: Any) -> bool:
    if not isinstance(details, dict):
        return False
    error = details.get("error", details)
    entries = error.get("details", []) if isinstance(error, dict) else []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or "QuotaFailure" not in str(
            entry.get("@type", "")
        ):
            continue
        violations = entry.get("violations", [])
        for violation in violations if isinstance(violations, list) else []:
            if not isinstance(violation, dict):
                continue
            quota_id = str(
                violation.get("quotaId") or violation.get("quota_id") or ""
            ).lower()
            if any(
                marker in quota_id
                for marker in ("perday", "daily", "billing", "hardproject")
            ):
                return True
    return False
