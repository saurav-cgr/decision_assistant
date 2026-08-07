from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from decision_assistant.errors import ApplicationError

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    provider: str
    model: str
    dimension: int


class EmbeddingProvider(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class GenerationProvider(Protocol):
    async def generate(
        self,
        prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT: ...


class ProviderError(ApplicationError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        details: Any | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=503 if retryable else 502,
            retryable=retryable,
            details=details,
        )


class ProviderUnavailable(ProviderError):
    def __init__(self, message: str = "Model provider unavailable") -> None:
        super().__init__(
            code="provider_unavailable",
            message=message,
            retryable=True,
        )


class ProviderResponseInvalid(ProviderError):
    def __init__(self, message: str = "Model provider returned invalid data") -> None:
        super().__init__(
            code="provider_response_invalid",
            message=message,
            retryable=False,
        )
