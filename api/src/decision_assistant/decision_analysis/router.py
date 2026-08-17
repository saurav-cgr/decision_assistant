from typing import Annotated

from fastapi import APIRouter, Depends

from decision_assistant.decision_analysis.schemas import (
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
)
from decision_assistant.decision_analysis.service import DecisionAnalysisService
from decision_assistant.providers.factory import (
    ProviderBundleFactory,
    get_provider_bundle_factory,
)

router = APIRouter(prefix="/api/v1/decision-analyses", tags=["decision-analyses"])


def get_decision_analysis_service(
    provider_factory: Annotated[
        ProviderBundleFactory, Depends(get_provider_bundle_factory)
    ],
) -> DecisionAnalysisService:
    return DecisionAnalysisService(
        generation_provider_factory=lambda: provider_factory().generation
    )


@router.post("", response_model=DecisionAnalysisResponse)
async def analyze_decision(
    request: DecisionAnalysisRequest,
    service: Annotated[
        DecisionAnalysisService, Depends(get_decision_analysis_service)
    ],
) -> DecisionAnalysisResponse:
    return await service.analyze(request)
