from typing import Annotated

from fastapi import APIRouter, Depends

from decision_assistant.decision_analysis.schemas import (
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
)
from decision_assistant.decision_analysis.service import DecisionAnalysisService

router = APIRouter(prefix="/api/v1/decision-analyses", tags=["decision-analyses"])


def get_decision_analysis_service() -> DecisionAnalysisService:
    return DecisionAnalysisService()


@router.post("", response_model=DecisionAnalysisResponse)
async def analyze_decision(
    request: DecisionAnalysisRequest,
    service: Annotated[
        DecisionAnalysisService, Depends(get_decision_analysis_service)
    ],
) -> DecisionAnalysisResponse:
    return service.analyze(request)
