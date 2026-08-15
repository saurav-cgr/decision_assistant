from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from threading import Lock
from typing import Any

from fastapi import Request

from decision_assistant.config import Settings
from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingProvider,
    GenerationProvider,
    ProviderConfigurationInvalid,
)
from decision_assistant.providers.gemini import (
    FIXED_EMBEDDING_DIMENSION,
    MAX_EMBEDDING_BATCH_SIZE,
    GeminiEmbeddingProvider,
    GeminiGenerationProvider,
)
from decision_assistant.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaGenerationProvider,
)


@dataclass(slots=True)
class ProviderBundle:
    embedding: EmbeddingProvider
    generation: GenerationProvider
    close_callback: Callable[[], Awaitable[None]] | None = None
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        if self.close_callback is not None:
            await self.close_callback()
        self._closed = True


@dataclass(slots=True)
class EmbeddingProviderHandle:
    embedding: EmbeddingProvider
    close_callback: Callable[[], Awaitable[None]] | None = None
    _closed: bool = False

    async def aclose(self) -> None:
        if self._closed:
            return
        if self.close_callback is not None:
            await self.close_callback()
        self._closed = True


ProviderBundleFactory = Callable[[], ProviderBundle]


def configured_embedding_profile(settings: Settings) -> EmbeddingProfile:
    """Validate selected embedding configuration without creating a client."""
    _prevalidate_embedding_settings(settings)
    if settings.embedding_provider == "gemini":
        return EmbeddingProfile(
            provider="gemini",
            model=settings.gemini_embedding_model,
            dimension=settings.gemini_embedding_dimension,
            adapter_config_version=settings.gemini_embedding_config_version,
        )
    return EmbeddingProfile(
        provider="ollama",
        model=settings.ollama_embedding_model,
        dimension=settings.ollama_embedding_dimension,
        adapter_config_version="ollama-native-v1",
    )


def validate_selected_provider_configuration(settings: Settings) -> None:
    """Check local configuration presence only; never create or call a provider."""
    _prevalidate_embedding_settings(settings)
    _prevalidate_generation_settings(settings)
    _prevalidate_rerank_settings(settings)
    if "gemini" in {settings.embedding_provider, settings.generation_provider}:
        key = (
            settings.gemini_api_key.get_secret_value().strip()
            if settings.gemini_api_key is not None
            else ""
        )
        if not key:
            raise ProviderConfigurationInvalid()


def _prevalidate_rerank_settings(settings: Settings) -> None:
    if settings.rerank_candidate_limit < 1 or settings.rerank_min_candidates < 1:
        raise ProviderConfigurationInvalid()
    if settings.rerank_final_limit < 1:
        raise ProviderConfigurationInvalid()
    if settings.rerank_final_limit > settings.rerank_candidate_limit:
        raise ProviderConfigurationInvalid()
    if settings.rerank_min_candidates > settings.rerank_candidate_limit:
        raise ProviderConfigurationInvalid()


class CachedProviderBundleFactory:
    def __init__(
        self,
        settings: Settings,
        *,
        builder: Callable[[Settings], ProviderBundle] = lambda settings: create_provider_bundle(settings),
    ) -> None:
        self._settings = settings
        self._builder = builder
        self._bundle: ProviderBundle | None = None
        self._initialization_lock = Lock()

    def __call__(self) -> ProviderBundle:
        if self._bundle is None:
            with self._initialization_lock:
                if self._bundle is None:
                    self._bundle = self._builder(self._settings)
        return self._bundle

    async def aclose(self) -> None:
        with self._initialization_lock:
            bundle = self._bundle
        if bundle is not None:
            await bundle.aclose()


def create_provider_bundle(
    settings: Settings,
    *,
    gemini_client: Any | None = None,
    gemini_client_factory: Callable[..., Any] | None = None,
) -> ProviderBundle:
    _prevalidate_embedding_settings(settings)
    _prevalidate_generation_settings(settings)

    client = gemini_client
    owns_client = False
    if "gemini" in {settings.embedding_provider, settings.generation_provider}:
        key = (
            settings.gemini_api_key.get_secret_value()
            if settings.gemini_api_key is not None
            else ""
        )
        if client is None and not key:
            raise ProviderConfigurationInvalid()
        if client is None:
            factory = gemini_client_factory or _create_gemini_client
            client = factory(
                api_key=key,
                timeout_seconds=settings.model_timeout_seconds,
            )
            owns_client = True

    if settings.embedding_provider == "gemini":
        embedding: EmbeddingProvider = GeminiEmbeddingProvider(
            client=client,
            model=settings.gemini_embedding_model,
            dimension=settings.gemini_embedding_dimension,
            adapter_config_version=settings.gemini_embedding_config_version,
            batch_size=settings.gemini_embedding_batch_size,
            retry_count=settings.model_retry_count,
            request_timeout_seconds=settings.model_timeout_seconds,
        )
    else:
        embedding = OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            dimension=settings.ollama_embedding_dimension,
            retry_count=settings.model_retry_count,
            timeout_seconds=settings.model_timeout_seconds,
        )

    if settings.generation_provider == "gemini":
        generation: GenerationProvider = GeminiGenerationProvider(
            client=client,
            model=settings.gemini_generation_model,
            prompt_version=settings.gemini_generation_prompt_version,
            max_prompt_characters=settings.gemini_max_prompt_characters,
            retry_count=settings.model_retry_count,
            request_timeout_seconds=settings.model_timeout_seconds,
        )
    else:
        generation = OllamaGenerationProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_generation_model,
            retry_count=settings.model_retry_count,
            timeout_seconds=settings.model_timeout_seconds,
            max_prompt_characters=settings.gemini_max_prompt_characters,
        )
    close_callback = _client_close_callback(client) if owns_client else None
    return ProviderBundle(
        embedding=embedding,
        generation=generation,
        close_callback=close_callback,
    )


def create_embedding_provider_handle(
    settings: Settings,
    *,
    gemini_client: Any | None = None,
    gemini_client_factory: Callable[..., Any] | None = None,
) -> EmbeddingProviderHandle:
    _prevalidate_embedding_settings(settings)

    client = gemini_client
    owns_client = False
    if settings.embedding_provider == "gemini":
        key = (
            settings.gemini_api_key.get_secret_value()
            if settings.gemini_api_key is not None
            else ""
        )
        if client is None and not key:
            raise ProviderConfigurationInvalid()
        if client is None:
            factory = gemini_client_factory or _create_gemini_client
            client = factory(
                api_key=key,
                timeout_seconds=settings.model_timeout_seconds,
            )
            owns_client = True
        embedding: EmbeddingProvider = GeminiEmbeddingProvider(
            client=client,
            model=settings.gemini_embedding_model,
            dimension=settings.gemini_embedding_dimension,
            adapter_config_version=settings.gemini_embedding_config_version,
            batch_size=settings.gemini_embedding_batch_size,
            retry_count=settings.model_retry_count,
            request_timeout_seconds=settings.model_timeout_seconds,
        )
    else:
        embedding = OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            dimension=settings.ollama_embedding_dimension,
            retry_count=settings.model_retry_count,
            timeout_seconds=settings.model_timeout_seconds,
        )

    return EmbeddingProviderHandle(
        embedding=embedding,
        close_callback=_client_close_callback(client) if owns_client else None,
    )


def _prevalidate_embedding_settings(settings: Settings) -> None:
    if settings.embedding_provider not in {"gemini", "ollama"}:
        raise ProviderConfigurationInvalid()
    if settings.model_retry_count < 0 or settings.model_timeout_seconds <= 0:
        raise ProviderConfigurationInvalid()

    if settings.embedding_provider == "gemini":
        if (
            settings.gemini_embedding_dimension != FIXED_EMBEDDING_DIMENSION
            or not 1
            <= settings.gemini_embedding_batch_size
            <= MAX_EMBEDDING_BATCH_SIZE
            or settings.gemini_embedding_config_version != "retrieval-prefix-v1"
            or not settings.gemini_embedding_model.strip()
        ):
            raise ProviderConfigurationInvalid()
        return

    if (
        settings.ollama_embedding_dimension != FIXED_EMBEDDING_DIMENSION
        or not settings.ollama_embedding_model.strip()
        or not settings.ollama_base_url.strip()
    ):
        raise ProviderConfigurationInvalid()


def _prevalidate_generation_settings(settings: Settings) -> None:
    if settings.generation_provider not in {"gemini", "ollama"}:
        raise ProviderConfigurationInvalid()
    if (
        settings.model_retry_count < 0
        or settings.model_timeout_seconds <= 0
        or settings.gemini_max_prompt_characters < 1
    ):
        raise ProviderConfigurationInvalid()

    if settings.generation_provider == "gemini":
        if (
            not settings.gemini_generation_model.strip()
            or not settings.gemini_generation_prompt_version.strip()
        ):
            raise ProviderConfigurationInvalid()
        return

    if (
        not settings.ollama_generation_model.strip()
        or not settings.ollama_base_url.strip()
    ):
        raise ProviderConfigurationInvalid()


def get_provider_bundle_factory(request: Request) -> ProviderBundleFactory:
    return request.app.state.provider_bundle_factory


def _client_close_callback(client: Any) -> Callable[[], Awaitable[None]]:
    aio_closed = False
    sync_closed = False

    async def close() -> None:
        nonlocal aio_closed, sync_closed
        errors: list[Exception] = []
        if not aio_closed:
            try:
                await client.aio.aclose()
            except Exception as exc:
                errors.append(exc)
            else:
                aio_closed = True
        if not sync_closed:
            try:
                client.close()
            except Exception as exc:
                errors.append(exc)
            else:
                sync_closed = True
        if errors:
            raise errors[0]

    return close


def _create_gemini_client(*, api_key: str, timeout_seconds: float) -> Any:
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version="v1beta",
            timeout=max(1, int(timeout_seconds * 1_000)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
