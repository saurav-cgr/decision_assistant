from dataclasses import replace

from decision_assistant.errors import ApplicationError
from decision_assistant.providers.base import (
    GenerationProvider,
    GenerationRequest,
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
    request: GenerationRequest,
    response_model: type[ResponseModelT],
) -> ResponseModelT:
    try:
        return await provider.generate(request, response_model)
    except ProviderOutputInvalid:
        repair_request = _repair_request(request)
        if repair_request.total_characters > provider.max_prompt_characters:
            raise ModelOutputInvalid() from None
        try:
            return await provider.generate(repair_request, response_model)
        except ProviderOutputInvalid:
            raise ModelOutputInvalid() from None


def _repair_request(request: GenerationRequest) -> GenerationRequest:
    return replace(
        request,
        system_instruction=(
            "REPAIR REQUIRED: The prior output did not match the supplied JSON schema. "
            "Return corrected structured data only.\n\n"
            f"{request.system_instruction}"
        ),
    )
