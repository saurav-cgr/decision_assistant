"""Generation half of the Gemini provider tests (DB53).

Split out of `test_gemini_provider.py` (embedding half) so both files stay under AGENTS.md's 500-line
cap; the shared fakes live in `tests/support/gemini_fakes.py`.
"""

import asyncio
import logging
import traceback
from typing import Any

import pytest
from google.genai import errors as genai_errors

from decision_assistant.providers.base import ProviderError, ProviderOutputInvalid
from tests.support.gemini_fakes import (
    GENERATION_MODEL,
    AnswerStub,
    RecordingModels,
    SdkError,
    config_payload,
    error_code,
    generation_provider,
    generation_response,
    request,
)


@pytest.mark.asyncio
async def test_generation_separates_trusted_and_user_roles() -> None:
    models = RecordingModels()
    models.generation_results.append(generation_response('{"answer":"supported"}'))

    result = await generation_provider(models).generate(
        request(user="Use evidence", system="trusted policy"),
        AnswerStub,
    )

    assert result == AnswerStub(answer="supported")
    call = models.generation_calls[0]
    assert call["model"] == GENERATION_MODEL
    assert call["contents"] == "Use evidence"
    config = config_payload(call["config"])
    assert config["temperature"] == 0
    assert config["system_instruction"] == "trusted policy"
    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] == AnswerStub.model_json_schema()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_output", ["not json", '{"answer": 7}', "{}"])
async def test_generation_rejects_malformed_or_schema_invalid_output(
    bad_output: str,
) -> None:
    models = RecordingModels()
    models.generation_results.append(generation_response(bad_output))

    with pytest.raises(ProviderOutputInvalid) as caught:
        await generation_provider(models).generate(request(), AnswerStub)

    assert error_code(caught) == "provider_response_invalid"


@pytest.mark.asyncio
async def test_generation_rejects_blank_roles_without_sdk_call() -> None:
    models = RecordingModels()

    with pytest.raises(ValueError, match="must not be blank"):
        request(user="   ", system="policy")
    with pytest.raises(ValueError, match="must not be blank"):
        request(user="prompt", system="   ")

    assert models.generation_calls == []


@pytest.mark.asyncio
async def test_generation_rejects_oversize_prompt_without_sdk_call() -> None:
    models = RecordingModels()

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models).generate(request("x" * 100_001), AnswerStub)

    assert error_code(caught) == "provider_input_too_large"
    assert models.generation_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_error",
    [
        TimeoutError("timed out"),
        SdkError(status_code=503),
        SdkError(status_code=429, retry_after=0.01),
    ],
)
async def test_generation_bounded_retry_recovers_from_transient_failures(
    first_error: Exception,
) -> None:
    models = RecordingModels()
    models.generation_results.extend(
        [first_error, generation_response('{"answer":"supported"}')]
    )

    result = await generation_provider(models).generate(request(), AnswerStub)

    assert result.answer == "supported"
    assert len(models.generation_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sdk_error", "expected_code"),
    [
        (
            SdkError(status_code=401, reason="API key rejected"),
            "provider_authentication_failed",
        ),
        (SdkError(status_code=429, retry_after=3600), "provider_rate_limited"),
        (
            SdkError(status_code=400, reason="schema unsupported"),
            "provider_schema_unsupported",
        ),
        (
            SdkError(status_code=422, reason="bad request"),
            "provider_response_invalid",
        ),
    ],
)
async def test_generation_maps_permanent_sdk_errors_to_distinct_sanitized_codes(
    sdk_error: SdkError,
    expected_code: str,
) -> None:
    models = RecordingModels()
    models.generation_results.append(sdk_error)

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models).generate(request(), AnswerStub)

    assert error_code(caught) == expected_code
    assert str(sdk_error) not in str(caught.value)


@pytest.mark.asyncio
async def test_exhausted_transient_retries_have_stable_unavailable_code() -> None:
    models = RecordingModels()
    models.generation_results.extend([TimeoutError("one"), TimeoutError("two")])

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models, retry_count=1).generate(request(), AnswerStub)

    assert error_code(caught) == "provider_unavailable"
    assert len(models.generation_calls) == 2


@pytest.mark.asyncio
async def test_exhausted_short_window_429_maps_to_rate_limited() -> None:
    models = RecordingModels()
    models.generation_results.extend(
        [
            SdkError(status_code=429, retry_after=0.01),
            SdkError(status_code=429, retry_after=0.01),
        ]
    )

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models, retry_count=1).generate(request(), AnswerStub)

    assert error_code(caught) == "provider_rate_limited"
    assert len(models.generation_calls) == 2


@pytest.mark.asyncio
async def test_api_key_never_appears_in_errors_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    key_name = "GEMINI_API_KEY"
    raw_value = "super-secret-value"
    models = RecordingModels()
    models.generation_results.append(
        SdkError(status_code=401, reason=f"{key_name}={raw_value}")
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as caught:
        await generation_provider(models).generate(request(), AnswerStub)

    assert key_name not in str(caught.value)
    assert raw_value not in str(caught.value)
    assert key_name not in caplog.text
    assert raw_value not in caplog.text


@pytest.mark.asyncio
async def test_sdk_secret_is_suppressed_from_formatted_traceback() -> None:
    secret = "traceback-secret-key"
    models = RecordingModels()
    models.generation_results.append(
        SdkError(status_code=401, reason=f"raw response contained {secret}")
    )

    try:
        await generation_provider(models).generate(request(), AnswerStub)
    except ProviderError as error:
        rendered = "".join(traceback.format_exception(error))
    else:
        raise AssertionError("ProviderError was not raised")

    assert secret not in rendered

@pytest.mark.asyncio
async def test_quota_marker_overrides_short_retry_after() -> None:
    models = RecordingModels()
    models.generation_results.append(
        SdkError(status_code=429, retry_after=0.01, reason="daily quota exhausted")
    )

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models).generate(request(), AnswerStub)

    assert caught.value.code == "provider_quota_exhausted"
    assert len(models.generation_calls) == 1


@pytest.mark.asyncio
async def test_rate_limit_is_not_retried_when_delay_exceeds_request_budget() -> None:
    models = RecordingModels()
    models.generation_results.append(
        SdkError(status_code=429, retry_after=2, reason="short rate limit")
    )

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models, request_timeout_seconds=1).generate(
            request(), AnswerStub
        )

    assert caught.value.code == "provider_rate_limited"
    assert len(models.generation_calls) == 1


@pytest.mark.asyncio
async def test_total_deadline_bounds_a_slow_sdk_attempt() -> None:
    class SlowModels(RecordingModels):
        async def generate_content(self, **kwargs: Any) -> Any:
            self.generation_calls.append(kwargs)
            await asyncio.sleep(0.1)
            return generation_response('{"answer":"too late"}')

    models = SlowModels()

    with pytest.raises(ProviderError) as caught:
        await generation_provider(
            models,
            request_timeout_seconds=0.01,
            retry_count=3,
        ).generate(request(), AnswerStub)

    assert caught.value.code == "provider_unavailable"
    assert len(models.generation_calls) == 1


@pytest.mark.asyncio
async def test_resource_exhausted_with_short_retry_after_remains_transient() -> None:
    models = RecordingModels()
    models.generation_results.extend(
        [
            SdkError(
                status_code=429,
                retry_after=0.01,
                reason="RESOURCE_EXHAUSTED",
            ),
            generation_response('{"answer":"supported"}'),
        ]
    )

    result = await generation_provider(models).generate(request(), AnswerStub)

    assert result.answer == "supported"
    assert len(models.generation_calls) == 2


@pytest.mark.asyncio
async def test_exponential_backoff_uses_bounded_injected_jitter() -> None:
    models = RecordingModels()
    models.generation_results.extend(
        [SdkError(status_code=503), generation_response('{"answer":"supported"}')]
    )
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    result = await generation_provider(
        models,
        retry_backoff_seconds=1,
        random_source=lambda: 1.0,
        sleep=record_sleep,
        request_timeout_seconds=10,
    ).generate(request(), AnswerStub)

    assert result.answer == "supported"
    assert delays == [pytest.approx(1.2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sdk_error",
    [
        SdkError(status_code=429, reason="RESOURCE_EXHAUSTED"),
        SdkError(status_code=429, retry_after=3600, reason="rate limit"),
    ],
)
async def test_429_without_usable_window_stays_nonretryable_rate_limit(
    sdk_error: SdkError,
) -> None:
    models = RecordingModels()
    models.generation_results.append(sdk_error)

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models).generate(request(), AnswerStub)

    assert caught.value.code == "provider_rate_limited"
    assert caught.value.retryable is False
    assert len(models.generation_calls) == 1


@pytest.mark.asyncio
async def test_actual_sdk_retry_info_shape_is_parsed() -> None:
    models = RecordingModels()
    models.generation_results.extend(
        [
            genai_errors.ClientError(
                429,
                {
                    "error": {
                        "code": 429,
                        "message": "Resource exhausted",
                        "status": "RESOURCE_EXHAUSTED",
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": "0.01s",
                            }
                        ],
                    }
                },
            ),
            generation_response('{"answer":"supported"}'),
        ]
    )

    result = await generation_provider(models).generate(request(), AnswerStub)

    assert result.answer == "supported"
    assert len(models.generation_calls) == 2


@pytest.mark.asyncio
async def test_actual_sdk_schema_rejection_maps_schema_unsupported() -> None:
    models = RecordingModels()
    models.generation_results.append(
        genai_errors.ClientError(
            400,
            {
                "error": {
                    "code": 400,
                    "message": "response_json_schema is unsupported",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )
    )

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models).generate(request(), AnswerStub)

    assert caught.value.code == "provider_schema_unsupported"


@pytest.mark.asyncio
async def test_actual_sdk_daily_quota_failure_id_maps_hard_quota() -> None:
    models = RecordingModels()
    models.generation_results.append(
        genai_errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "Quota exceeded",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {
                                    "quotaId": (
                                        "GenerateRequestsPerDayPerProjectPerModel-"
                                        "FreeTier"
                                    )
                                }
                            ],
                        }
                    ],
                }
            },
        )
    )

    with pytest.raises(ProviderError) as caught:
        await generation_provider(models).generate(request(), AnswerStub)

    assert caught.value.code == "provider_quota_exhausted"


@pytest.mark.asyncio
async def test_schema_indicator_in_value_error_maps_schema_without_leaking() -> None:
    secret = "schema-secret-body"
    models = RecordingModels()
    models.generation_results.append(
        ValueError(f"response schema unsupported: {secret}")
    )

    caught_error: ProviderError | None = None
    try:
        await generation_provider(models).generate(request(), AnswerStub)
    except ProviderError as error:
        caught_error = error
        rendered = "".join(traceback.format_exception(error))
    else:
        raise AssertionError("ProviderError was not raised")

    assert caught_error is not None
    assert caught_error.code == "provider_schema_unsupported"
    assert secret not in rendered
