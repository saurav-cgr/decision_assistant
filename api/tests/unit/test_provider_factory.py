from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from time import sleep
from typing import Any, get_type_hints

import pytest

from decision_assistant.answering.router import get_answer_service
from decision_assistant.config import Settings
from decision_assistant.documents.router import get_document_service
from decision_assistant.evaluation.router import get_evaluation_service
from decision_assistant.providers.base import ProviderError
from decision_assistant.providers.factory import (
    CachedProviderBundleFactory,
    EmbeddingProviderHandle,
    ProviderBundle,
    create_embedding_provider_handle,
    create_provider_bundle,
    get_provider_bundle_factory,
)
from decision_assistant.providers.gemini import (
    GeminiEmbeddingProvider,
    GeminiGenerationProvider,
)
from decision_assistant.providers.ollama import (
    OllamaEmbeddingProvider,
    OllamaGenerationProvider,
)
from decision_assistant.retrieval.router import get_retrieval_service
from decision_assistant.providers.fakes import (
    FakeEmbeddingProvider,
    FakeGenerationProvider,
)


PROJECT_ROOT = Path(__file__).parents[3]
CURRENT_FREE_TIER_GENERATION_MODEL = "gemini-3.1-flash-lite"


def test_default_generation_model_is_current_and_consistent_across_runtime_config() -> None:
    assert (
        Settings.model_fields["gemini_generation_model"].default
        == CURRENT_FREE_TIER_GENERATION_MODEL
    )
    assert (
        f"GEMINI_GENERATION_MODEL={CURRENT_FREE_TIER_GENERATION_MODEL}"
        in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    )
    assert (
        "GEMINI_GENERATION_MODEL: "
        f"${{GEMINI_GENERATION_MODEL:-{CURRENT_FREE_TIER_GENERATION_MODEL}}}"
        in (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    )


def gemini_settings(**overrides: Any) -> Settings:
    values = {
        "generation_provider": "gemini",
        "embedding_provider": "gemini",
        "gemini_api_key": "test-key",
        "gemini_generation_model": "gemini-3.1-flash-lite",
        "gemini_embedding_model": "gemini-embedding-2",
        "gemini_embedding_dimension": 768,
        "gemini_embedding_config_version": "retrieval-prefix-v1",
        "gemini_generation_prompt_version": "gemini-json-v1",
        "gemini_embedding_batch_size": 32,
        "gemini_max_prompt_characters": 100_000,
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_construction_does_not_require_live_provider_credentials() -> None:
    settings = gemini_settings(gemini_api_key=None)

    assert settings.gemini_api_key is None


def test_factory_selects_gemini_for_both_provider_interfaces() -> None:
    client = object()

    bundle = create_provider_bundle(gemini_settings(), gemini_client=client)

    assert isinstance(bundle.embedding, GeminiEmbeddingProvider)
    assert isinstance(bundle.generation, GeminiGenerationProvider)
    assert bundle.embedding.profile.dimension == 768


def test_missing_key_fails_only_when_live_bundle_is_requested() -> None:
    settings = gemini_settings(gemini_api_key=None)

    with pytest.raises(ProviderError) as caught:
        create_provider_bundle(settings)

    assert caught.value.code == "provider_configuration_invalid"


def test_non_768_gemini_dimension_is_rejected_before_client_creation() -> None:
    client_factory_calls = 0

    def client_factory(*_: Any, **__: Any) -> object:
        nonlocal client_factory_calls
        client_factory_calls += 1
        return object()

    with pytest.raises(ProviderError) as caught:
        create_provider_bundle(
            gemini_settings(gemini_embedding_dimension=384),
            gemini_client_factory=client_factory,
        )

    assert caught.value.code == "provider_configuration_invalid"
    assert client_factory_calls == 0


def test_non_768_ollama_dimension_is_rejected_before_adapter_construction() -> None:
    with pytest.raises(ProviderError) as caught:
        create_provider_bundle(
            gemini_settings(
                embedding_provider="ollama",
                generation_provider="ollama",
                gemini_api_key=None,
                ollama_embedding_dimension=384,
            )
        )

    assert caught.value.code == "provider_configuration_invalid"


def test_factory_preserves_optional_ollama_selection() -> None:
    settings = gemini_settings(
        generation_provider="ollama",
        embedding_provider="ollama",
        gemini_api_key=None,
    )

    bundle = create_provider_bundle(settings)

    assert isinstance(bundle.embedding, OllamaEmbeddingProvider)
    assert isinstance(bundle.generation, OllamaGenerationProvider)


def test_embedding_only_factory_ignores_unselected_gemini_generation_credentials() -> None:
    handle = create_embedding_provider_handle(
        gemini_settings(
            embedding_provider="ollama",
            generation_provider="gemini",
            gemini_api_key=None,
        )
    )

    assert isinstance(handle.embedding, OllamaEmbeddingProvider)


@pytest.mark.asyncio
async def test_embedding_only_factory_closes_owned_gemini_client_once() -> None:
    aio_close_calls = 0
    sync_close_calls = 0

    class AioClient:
        models = object()

        async def aclose(self) -> None:
            nonlocal aio_close_calls
            aio_close_calls += 1

    class Client:
        aio = AioClient()

        def close(self) -> None:
            nonlocal sync_close_calls
            sync_close_calls += 1

    handle = create_embedding_provider_handle(
        gemini_settings(),
        gemini_client_factory=lambda **_: Client(),
    )

    assert isinstance(handle, EmbeddingProviderHandle)
    await handle.aclose()
    await handle.aclose()
    assert aio_close_calls == 1
    assert sync_close_calls == 1


def test_embedding_only_factory_prevalidates_before_client_creation() -> None:
    client_factory_calls = 0

    def client_factory(**_: Any) -> object:
        nonlocal client_factory_calls
        client_factory_calls += 1
        return object()

    with pytest.raises(ProviderError) as caught:
        create_embedding_provider_handle(
            gemini_settings(gemini_embedding_batch_size=0),
            gemini_client_factory=client_factory,
        )

    assert caught.value.code == "provider_configuration_invalid"
    assert client_factory_calls == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_retry_count": -1},
        {
            "embedding_provider": "ollama",
            "generation_provider": "gemini",
            "gemini_max_prompt_characters": 0,
        },
    ],
)
def test_full_factory_prevalidates_selected_adapters_before_client_creation(
    overrides: dict[str, Any],
) -> None:
    client_factory_calls = 0

    def client_factory(**_: Any) -> object:
        nonlocal client_factory_calls
        client_factory_calls += 1
        return object()

    with pytest.raises(ProviderError) as caught:
        create_provider_bundle(
            gemini_settings(**overrides),
            gemini_client_factory=client_factory,
        )

    assert caught.value.code == "provider_configuration_invalid"
    assert client_factory_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("generation_provider", "unknown"), ("embedding_provider", "unknown")],
)
def test_factory_rejects_unsupported_provider(field: str, value: str) -> None:
    with pytest.raises(ProviderError) as caught:
        create_provider_bundle(gemini_settings(**{field: value}))

    assert caught.value.code == "provider_configuration_invalid"


def test_all_provider_backed_routes_share_one_overridable_dependency() -> None:
    for service_factory in (
        get_document_service,
        get_answer_service,
        get_retrieval_service,
        get_evaluation_service,
    ):
        hints = get_type_hints(service_factory, include_extras=True)
        annotation = hints["provider_factory"]
        dependencies = [
            item for item in annotation.__metadata__ if hasattr(item, "dependency")
        ]
        assert len(dependencies) == 1
        assert dependencies[0].dependency is get_provider_bundle_factory


@pytest.mark.asyncio
async def test_cached_bundle_is_created_once_and_closed_once() -> None:
    close_calls = 0

    async def close() -> None:
        nonlocal close_calls
        close_calls += 1

    bundle = ProviderBundle(
        embedding=FakeEmbeddingProvider(),
        generation=FakeGenerationProvider(),
        close_callback=close,
    )
    create_calls = 0

    def build(_: Settings) -> ProviderBundle:
        nonlocal create_calls
        create_calls += 1
        return bundle

    factory = CachedProviderBundleFactory(gemini_settings(), builder=build)

    assert factory() is bundle
    assert factory() is bundle
    await factory.aclose()
    await factory.aclose()

    assert create_calls == 1
    assert close_calls == 1


@pytest.mark.asyncio
async def test_owned_gemini_aio_and_sync_clients_close_exactly_once() -> None:
    aio_close_calls = 0
    sync_close_calls = 0

    class AioClient:
        models = object()

        async def aclose(self) -> None:
            nonlocal aio_close_calls
            aio_close_calls += 1

    class Client:
        aio = AioClient()

        def close(self) -> None:
            nonlocal sync_close_calls
            sync_close_calls += 1

    bundle = create_provider_bundle(
        gemini_settings(),
        gemini_client_factory=lambda **_: Client(),
    )

    await bundle.aclose()
    await bundle.aclose()

    assert aio_close_calls == 1
    assert sync_close_calls == 1


@pytest.mark.asyncio
async def test_client_cleanup_attempts_both_legs_and_retries_only_failed_leg() -> None:
    aio_close_calls = 0
    sync_close_calls = 0

    class AioClient:
        models = object()

        async def aclose(self) -> None:
            nonlocal aio_close_calls
            aio_close_calls += 1
            if aio_close_calls == 1:
                raise RuntimeError("temporary aio close failure")

    class Client:
        aio = AioClient()

        def close(self) -> None:
            nonlocal sync_close_calls
            sync_close_calls += 1

    bundle = create_provider_bundle(
        gemini_settings(),
        gemini_client_factory=lambda **_: Client(),
    )

    with pytest.raises(RuntimeError, match="aio close failure"):
        await bundle.aclose()
    await bundle.aclose()
    await bundle.aclose()

    assert aio_close_calls == 2
    assert sync_close_calls == 1


@pytest.mark.asyncio
async def test_concurrent_first_use_builds_one_bundle_without_leak() -> None:
    first_builder_entered = Event()
    second_caller_ready = Event()
    count_lock = Lock()
    build_calls = 0
    close_calls = 0

    async def close() -> None:
        nonlocal close_calls
        close_calls += 1

    bundle = ProviderBundle(
        embedding=FakeEmbeddingProvider(),
        generation=FakeGenerationProvider(),
        close_callback=close,
    )

    def build(_: Settings) -> ProviderBundle:
        nonlocal build_calls
        with count_lock:
            build_calls += 1
            call_number = build_calls
        if call_number == 1:
            first_builder_entered.set()
            assert second_caller_ready.wait(timeout=1)
            sleep(0.05)
        return bundle

    factory = CachedProviderBundleFactory(gemini_settings(), builder=build)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(factory)
        assert first_builder_entered.wait(timeout=1)

        def second_call() -> ProviderBundle:
            second_caller_ready.set()
            return factory()

        second = executor.submit(second_call)
        first_result = first.result(timeout=2)
        second_result = second.result(timeout=2)

    await factory.aclose()

    assert first_result is bundle
    assert second_result is bundle
    assert build_calls == 1
    assert close_calls == 1
