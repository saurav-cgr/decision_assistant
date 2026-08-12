from decision_assistant.errors import ApplicationError
from decision_assistant.providers.base import (
    GenerationProvider,
    ProviderOutputInvalid,
    ResponseModelT,
)


class ModelOutputInvalid(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="model_output_invalid",
            message="Model output did not match the required schema",
            status_code=502,
            retryable=False,
        )


async def generate_with_repair(
    provider: GenerationProvider,
    prompt: str,
    response_model: type[ResponseModelT],
) -> ResponseModelT:
    try:
        return await provider.generate(prompt, response_model)
    except ProviderOutputInvalid:
        repair_prompt = _repair_prompt(prompt)
        if len(repair_prompt) > provider.max_prompt_characters:
            raise ModelOutputInvalid() from None
        try:
            return await provider.generate(repair_prompt, response_model)
        except ProviderOutputInvalid:
            raise ModelOutputInvalid() from None


def _repair_prompt(prompt: str) -> str:
    return (
        "REPAIR REQUIRED: The prior output did not match the supplied JSON schema. "
        "Return corrected structured data only.\n\n"
        f"{prompt}"
    )
