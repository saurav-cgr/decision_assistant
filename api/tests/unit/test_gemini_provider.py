"""Embedding half of the Gemini provider tests.

The generation half lives in `test_gemini_generation.py`, and the shared fakes in
`tests/support/gemini_fakes.py`, so each file stays under AGENTS.md's 500-line cap (DB53).
"""

import math
from typing import Any

import pytest

from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingPurpose,
    GenerationProfile,
    ProviderError,
)
from tests.support.gemini_fakes import (
    DIMENSION,
    EMBEDDING_MODEL,
    GENERATION_MODEL,
    RecordingModels,
    SdkError,
    config_payload,
    embedding_provider,
    embedding_response,
    error_code,
    generation_provider,
)


def test_profiles_fully_describe_the_embedding_and_generation_contracts() -> None:
    models = RecordingModels()

    assert embedding_provider(models).profile == EmbeddingProfile(
        provider="gemini",
        model=EMBEDDING_MODEL,
        dimension=DIMENSION,
        adapter_config_version="retrieval-prefix-v1",
    )
    assert generation_provider(models).profile == GenerationProfile(
        provider="gemini",
        model=GENERATION_MODEL,
        api_version="v1beta",
        sdk_version="2.13.0",
        temperature=0,
        schema_mode="json_schema",
        prompt_contract_version="gemini-json-v2",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("purpose", "text", "formatted"),
    [
        (EmbeddingPurpose.DOCUMENT, "Evidence", "title: none | text: Evidence"),
        (
            EmbeddingPurpose.QUERY,
            "authentication",
            "task: search result | query: authentication",
        ),
    ],
)
async def test_embedding_formats_by_purpose_without_unsupported_task_type(
    purpose: EmbeddingPurpose,
    text: str,
    formatted: str,
) -> None:
    models = RecordingModels()
    models.embedding_results.append(embedding_response([[0.0] * DIMENSION]))

    await embedding_provider(models).embed([text], purpose=purpose)

    assert models.embedding_calls[0]["model"] == EMBEDDING_MODEL
    assert models.embedding_calls[0]["contents"] == [
        {"role": "user", "parts": [{"text": formatted}]}
    ]
    config = config_payload(models.embedding_calls[0]["config"])
    assert config["output_dimensionality"] == DIMENSION
    assert "task_type" not in config


@pytest.mark.asyncio
async def test_embedding_splits_at_32_and_preserves_application_order() -> None:
    models = RecordingModels()
    expected = [[float(index)] + [0.0] * (DIMENSION - 1) for index in range(70)]
    models.embedding_results.extend(
        embedding_response(expected[start : start + 32])
        for start in range(0, len(expected), 32)
    )

    actual = await embedding_provider(models).embed(
        [f"passage {index}" for index in range(70)],
        purpose=EmbeddingPurpose.DOCUMENT,
    )

    assert [len(call["contents"]) for call in models.embedding_calls] == [32, 32, 6]
    assert [call["contents"] for call in models.embedding_calls] == [
        [
            {
                "role": "user",
                "parts": [{"text": f"title: none | text: passage {index}"}],
            }
            for index in range(start, min(start + 32, 70))
        ]
        for start in (0, 32, 64)
    ]
    assert actual == expected
    assert [vector[0] for vector in actual] == [float(index) for index in range(70)]


@pytest.mark.asyncio
async def test_embedding_retries_a_transient_provider_failure() -> None:
    models = RecordingModels()
    vector = [0.0] * DIMENSION
    models.embedding_results.extend(
        [SdkError(status_code=503), embedding_response([vector])]
    )

    result = await embedding_provider(models).embed(
        ["evidence"], purpose=EmbeddingPurpose.DOCUMENT
    )

    assert result == [vector]
    assert len(models.embedding_calls) == 2


@pytest.mark.asyncio
async def test_embedding_rejects_empty_application_batch_without_sdk_call() -> None:
    models = RecordingModels()

    with pytest.raises(ValueError, match="at least one"):
        await embedding_provider(models).embed(
            [], purpose=EmbeddingPurpose.DOCUMENT
        )

    assert models.embedding_calls == []


@pytest.mark.asyncio
async def test_embedding_rejects_oversize_input_without_calling_sdk() -> None:
    models = RecordingModels()
    provider = embedding_provider(models, max_input_characters=10)

    with pytest.raises(ProviderError) as caught:
        await provider.embed(["x" * 11], purpose=EmbeddingPurpose.DOCUMENT)

    assert error_code(caught) == "provider_input_too_large"
    assert models.embedding_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[0.0] * DIMENSION, [1.0] * DIMENSION],
        [[0.0] * (DIMENSION - 1)],
        [[0.0] * (DIMENSION + 1)],
        [[0.0] * (DIMENSION - 1) + [math.nan]],
        [[0.0] * (DIMENSION - 1) + [math.inf]],
        [[0.0] * (DIMENSION - 1) + [True]],
        [[0.0] * (DIMENSION - 1) + ["0"]],
    ],
)
async def test_embedding_validates_cardinality_dimension_and_finite_numbers(
    vectors: list[list[Any]],
) -> None:
    models = RecordingModels()
    models.embedding_results.append(embedding_response(vectors))

    with pytest.raises(ProviderError) as caught:
        await embedding_provider(models).embed(
            ["evidence"], purpose=EmbeddingPurpose.DOCUMENT
        )

    assert error_code(caught) == "provider_response_invalid"


def test_embedding_rejects_non_schema_dimension_before_provider_call() -> None:
    models = RecordingModels()

    with pytest.raises(ProviderError) as caught:
        embedding_provider(models, dimension=384)

    assert error_code(caught) == "provider_configuration_invalid"
    assert models.embedding_calls == []


def test_embedding_rejects_sdk_batch_size_above_32() -> None:
    models = RecordingModels()

    with pytest.raises(ProviderError) as caught:
        embedding_provider(models, batch_size=33)

    assert error_code(caught) == "provider_configuration_invalid"
    assert models.embedding_calls == []

