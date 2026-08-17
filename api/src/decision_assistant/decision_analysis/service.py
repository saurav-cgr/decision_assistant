from decision_assistant.decision_analysis.schemas import (
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
)
from decision_assistant.decision_analysis.scoring import calculate_decision
from decision_assistant.decision_analysis.verifier import DecisionAnalysisVerifier


class DecisionAnalysisService:
    def __init__(self, verifier: DecisionAnalysisVerifier | None = None) -> None:
        self._verifier = verifier or DecisionAnalysisVerifier()

    def analyze(self, request: DecisionAnalysisRequest) -> DecisionAnalysisResponse:
        response = calculate_decision(request)
        verification = self._verifier.verify(request, response)
        return response.model_copy(update={"verification": verification})
