from typing import Any, Protocol
from uuid import UUID

from decision_assistant.evaluation.models import EvaluationQuestion
from decision_assistant.providers.base import GenerationRequest


class EvaluationExecutor(Protocol):
    async def execute(
        self,
        question: EvaluationQuestion,
        *,
        run_id: UUID,
        strategy: str,
        configuration: dict[str, Any],
    ) -> dict[str, Any]: ...


class ClaimSupportJudge(Protocol):
    async def judge(
        self,
        request: GenerationRequest,
        *,
        profile: dict[str, Any],
    ) -> dict[str, Any]: ...
