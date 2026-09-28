from dataclasses import asdict
from typing import Any

from decision_assistant.evaluation.schemas import ClaimJudgeOutput
from decision_assistant.providers.base import GenerationProvider, GenerationRequest
from decision_assistant.providers.orchestration import generate_with_repair


class GenerationClaimJudge:
    def __init__(self, provider: GenerationProvider) -> None:
        self._provider = provider

    @property
    def profile(self) -> dict[str, Any]:
        return asdict(self._provider.profile)

    async def judge(
        self,
        request: GenerationRequest,
        *,
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        del profile
        result = await generate_with_repair(
            self._provider,
            request,
            ClaimJudgeOutput,
        )
        return result.model_dump(mode="json")
