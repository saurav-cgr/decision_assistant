from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from decision_assistant.errors import ApplicationError

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class EmbeddingPurpose(StrEnum):
    DOCUMENT = "document"
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    provider: str
    model: str
    dimension: int
    adapter_config_version: str

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GenerationProfile:
    provider: str
    model: str
    api_version: str
    sdk_version: str
    temperature: int
    schema_mode: str
    prompt_contract_version: str


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """Trusted system instructions vs request-specific untrusted user content.

    ``system_instruction`` carries stable application policy (task/role,
    evidence-only behavior, untrusted-content rule, citation and abstention
    rules). ``user_content`` carries only request-specific data (questions,
    document passages, candidates, judge payloads). Repair never alters
    ``user_content`` byte-for-byte.
    """

    system_instruction: str
    user_content: str

    def __post_init__(self) -> None:
        if not self.system_instruction.strip():
            raise ValueError("system_instruction must not be blank")
        if not self.user_content.strip():
            raise ValueError("user_content must not be blank")

    @property
    def total_characters(self) -> int:
        return len(self.system_instruction) + len(self.user_content)


class EmbeddingProvider(Protocol):
    @property
    def profile(self) -> EmbeddingProfile: ...

    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]: ...


class GenerationProvider(Protocol):
    @property
    def profile(self) -> GenerationProfile: ...

    @property
    def max_prompt_characters(self) -> int: ...

    async def generate(
        self,
        request: GenerationRequest,
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


class ProviderOutputInvalid(ProviderResponseInvalid):
    """Locally received generation output failed JSON/schema validation."""



class ProviderConfigurationInvalid(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            code="provider_configuration_invalid",
            message="Model provider configuration is invalid",
            retryable=False,
        )


class ProviderAuthenticationFailed(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            code="provider_authentication_failed",
            message="Model provider authentication failed",
            retryable=False,
        )


class ProviderRateLimited(ProviderError):
    def __init__(self, *, retryable: bool = True) -> None:
        super().__init__(
            code="provider_rate_limited",
            message="Model provider rate limit reached",
            retryable=retryable,
        )


class ProviderQuotaExhausted(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            code="provider_quota_exhausted",
            message="Model provider quota exhausted",
            retryable=False,
        )


class ProviderInputTooLarge(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            code="provider_input_too_large",
            message="Model provider input exceeds the configured limit",
            retryable=False,
        )


class ProviderSchemaUnsupported(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            code="provider_schema_unsupported",
            message="Model provider does not support the response schema",
            retryable=False,
        )
