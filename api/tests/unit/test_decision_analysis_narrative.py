from decimal import Decimal

import pytest

from decision_assistant.decision_analysis.narrative import build_narrative_request
from decision_assistant.decision_analysis.schemas import SensitivityRequest
from decision_assistant.decision_analysis.service import DecisionAnalysisService
from decision_assistant.providers.fakes import FakeGenerationProvider
from tests.unit.test_decision_analysis_scoring import request_for


@pytest.mark.asyncio
async def test_narrative_uses_verified_data_and_cannot_change_winner() -> None:
    provider = FakeGenerationProvider(
        [
            {
                "recommendation_option_id": "managed",
                "summary": "Managed wins on weighted quality.",
                "dominant_criterion_ids": ["quality"],
                "tradeoffs": ["Self-hosted costs less."],
                "assumptions": ["Inputs are user-provided."],
            }
        ]
    )
    service = DecisionAnalysisService(
        generation_provider_factory=lambda: provider
    )

    result = await service.analyze(request_for(narrative_requested=True))

    assert result.narrative_status == "generated"
    assert result.narrative is not None
    assert result.narrative.recommendation_option_id == "managed"
    assert provider.requests[0].system_instruction.startswith(
        "You explain a completed deterministic decision analysis."
    )
    assert "managed" in provider.requests[0].user_content
    assert "user-provided scores affect the ranking" in provider.requests[0].user_content


@pytest.mark.asyncio
async def test_invalid_narrative_falls_back_to_verified_result() -> None:
    provider = FakeGenerationProvider(
        [
            {
                "recommendation_option_id": "self_hosted",
                "summary": "Self-hosted wins.",
                "dominant_criterion_ids": ["unknown"],
            }
        ]
    )
    service = DecisionAnalysisService(
        generation_provider_factory=lambda: provider
    )

    result = await service.analyze(request_for(narrative_requested=True))

    assert result.narrative is None
    assert result.narrative_status == "unavailable"
    assert result.ranked_options[0].option_id == "managed"


@pytest.mark.asyncio
async def test_no_narrative_request_never_creates_provider() -> None:
    calls = 0

    def provider_factory():
        nonlocal calls
        calls += 1
        raise AssertionError("provider must not be created")

    result = await DecisionAnalysisService(
        generation_provider_factory=provider_factory
    ).analyze(
        request_for(sensitivity=SensitivityRequest(range_percent=Decimal("0.2")))
    )

    assert result.narrative_status == "not_requested"
    assert calls == 0


def test_narrative_prompt_keeps_verified_payload_out_of_system_role() -> None:
    from decision_assistant.decision_analysis.scoring import calculate_decision

    response = calculate_decision(request_for())
    request = build_narrative_request(response)

    assert "untrusted data" in request.system_instruction
    assert "managed" not in request.system_instruction
    assert "managed" in request.user_content
