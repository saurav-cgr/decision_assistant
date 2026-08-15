import pytest
from pydantic import BaseModel

from decision_assistant.providers.base import (
    GenerationRequest,
    ProviderOutputInvalid,
    ProviderResponseInvalid,
)
from decision_assistant.providers.fakes import FakeGenerationProvider
from decision_assistant.providers.orchestration import (
    ModelOutputInvalid,
    generate_with_repair,
)


class Output(BaseModel):
    value: str


def request(user: str = "original", system: str = "policy") -> GenerationRequest:
    return GenerationRequest(system_instruction=system, user_content=user)


@pytest.mark.asyncio
async def test_schema_invalid_output_is_repaired_once() -> None:
    provider = FakeGenerationProvider(
        [ProviderOutputInvalid(), {"value": "fixed"}]
    )

    result = await generate_with_repair(provider, request(), Output)

    assert result == Output(value="fixed")
    assert len(provider.requests) == 2
    assert "REPAIR REQUIRED" in provider.requests[1].system_instruction


@pytest.mark.asyncio
async def test_repair_preserves_user_content_byte_for_byte() -> None:
    user = "evidence: <passage>secret</passage>"
    provider = FakeGenerationProvider([ProviderOutputInvalid(), {"value": "fixed"}])

    await generate_with_repair(provider, request(user=user), Output)

    assert provider.requests[0].user_content == user
    assert provider.requests[1].user_content == user
    assert provider.requests[0].system_instruction == "policy"
    assert "REPAIR REQUIRED" in provider.requests[1].system_instruction


@pytest.mark.asyncio
async def test_second_schema_invalid_output_has_stable_terminal_error() -> None:
    provider = FakeGenerationProvider(
        [ProviderOutputInvalid(), ProviderOutputInvalid()]
    )

    with pytest.raises(ModelOutputInvalid) as caught:
        await generate_with_repair(provider, request(), Output)

    assert caught.value.code == "model_output_invalid"
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_request_shape_error_is_not_repaired() -> None:
    provider = FakeGenerationProvider([ProviderResponseInvalid()])

    with pytest.raises(ProviderResponseInvalid):
        await generate_with_repair(provider, request(), Output)

    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_repair_respects_provider_prompt_ceiling_without_oversized_call() -> None:
    provider = FakeGenerationProvider(
        [ProviderOutputInvalid()],
        max_prompt_characters=len("policyoriginal"),
    )

    with pytest.raises(ModelOutputInvalid):
        await generate_with_repair(provider, request(), Output)

    assert provider.requests == [request()]
