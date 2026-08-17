from collections.abc import Callable

from decision_assistant.decision_analysis.narrative import (
    build_narrative_request,
    verify_narrative,
)
from decision_assistant.decision_analysis.schemas import (
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
    GeneratedDecisionNarrative,
    NarrativeStatus,
)
from decision_assistant.decision_analysis.scoring import calculate_decision
from decision_assistant.decision_analysis.verifier import DecisionAnalysisVerifier
from decision_assistant.providers.base import GenerationProvider, ProviderError


class DecisionAnalysisService:
    def __init__(
        self,
        verifier: DecisionAnalysisVerifier | None = None,
        generation_provider_factory: Callable[[], GenerationProvider] | None = None,
    ) -> None:
        self._verifier = verifier or DecisionAnalysisVerifier()
        self._generation_provider_factory = generation_provider_factory

    async def analyze(
        self, request: DecisionAnalysisRequest
    ) -> DecisionAnalysisResponse:
        response = calculate_decision(request)
        verification = self._verifier.verify(request, response)
        verified = response.model_copy(update={"verification": verification})
        if not request.narrative_requested:
            return verified
        if self._generation_provider_factory is None:
            return verified.model_copy(
                update={"narrative_status": NarrativeStatus.UNAVAILABLE}
            )
        try:
            narrative = await self._generation_provider_factory().generate(
                build_narrative_request(verified), GeneratedDecisionNarrative
            )
        except ProviderError:
            return verified.model_copy(
                update={"narrative_status": NarrativeStatus.UNAVAILABLE}
            )
        if verify_narrative(narrative, verified):
            return verified.model_copy(
                update={"narrative_status": NarrativeStatus.UNAVAILABLE}
            )
        return verified.model_copy(
            update={
                "narrative": narrative,
                "narrative_status": NarrativeStatus.GENERATED,
            }
        )
