import pytest
from pydantic import BaseModel

from decision_assistant.providers.base import (
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


@pytest.mark.asyncio
async def test_schema_invalid_output_is_repaired_once() -> None:
    provider = FakeGenerationProvider(
        [ProviderOutputInvalid(), {"value": "fixed"}]
    )

    result = await generate_with_repair(provider, "original", Output)

    assert result == Output(value="fixed")
    assert len(provider.prompts) == 2
    assert "REPAIR REQUIRED" in provider.prompts[1]


@pytest.mark.asyncio
async def test_second_schema_invalid_output_has_stable_terminal_error() -> None:
    provider = FakeGenerationProvider(
        [ProviderOutputInvalid(), ProviderOutputInvalid()]
    )

    with pytest.raises(ModelOutputInvalid) as caught:
        await generate_with_repair(provider, "original", Output)

    assert caught.value.code == "model_output_invalid"
    assert len(provider.prompts) == 2


@pytest.mark.asyncio
async def test_request_shape_error_is_not_repaired() -> None:
    provider = FakeGenerationProvider([ProviderResponseInvalid()])

    with pytest.raises(ProviderResponseInvalid):
        await generate_with_repair(provider, "original", Output)

    assert len(provider.prompts) == 1


@pytest.mark.asyncio
async def test_repair_respects_provider_prompt_ceiling_without_oversized_call() -> None:
    provider = FakeGenerationProvider(
        [ProviderOutputInvalid()],
        max_prompt_characters=len("original"),
    )

    with pytest.raises(ModelOutputInvalid):
        await generate_with_repair(provider, "original", Output)

    assert provider.prompts == ["original"]
