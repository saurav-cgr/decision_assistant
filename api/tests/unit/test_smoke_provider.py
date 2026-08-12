import json
from hashlib import sha256
from uuid import uuid4

import pytest

from decision_assistant.answering.schemas import GeneratedAnswerCandidate
from decision_assistant.decisions.schemas import DecisionExtractionResponse
from decision_assistant.providers.base import EmbeddingPurpose
from tests.support.smoke_provider import (
    SmokeEmbeddingProvider,
    SmokeGenerationProvider,
)


@pytest.mark.asyncio
async def test_smoke_embedding_provider_is_offline_and_uses_schema_dimension() -> None:
    provider = SmokeEmbeddingProvider()

    vectors = await provider.embed(
        ["authentication", "authentication"],
        purpose=EmbeddingPurpose.QUERY,
    )

    assert provider.profile.provider == "smoke-fake"
    assert provider.profile.dimension == 768
    assert len(vectors) == 2
    assert vectors[0] == vectors[1]
    assert len(vectors[0]) == 768


@pytest.mark.asyncio
async def test_smoke_generation_extracts_only_fixed_atlas_beta_decision() -> None:
    passage_id = uuid4()
    content = (
        "Proposal: Start an employee-only authentication beta on July 15, 2026, "
        "using the existing OpenID Connect provider. Status: proposed. Priya Nair "
        "is the decision owner."
    )
    prompt = f'<passage id="{passage_id}">\n{content}\n</passage>'

    result = await SmokeGenerationProvider().generate(
        prompt,
        DecisionExtractionResponse,
    )

    assert len(result.decisions) == 1
    assert result.decisions[0].status == "proposed"
    assert result.decisions[0].owner == "Priya Nair"
    assert result.decisions[0].topic == "authentication"
    assert result.decisions[0].evidence.passage_id == passage_id
    assert result.decisions[0].evidence.quote in content


@pytest.mark.asyncio
async def test_smoke_generation_builds_verifiable_answer_from_prompt_evidence() -> None:
    passage_id = uuid4()
    content = (
        "This accepted revision supersedes the June 12 proposal to begin the "
        "internal beta on July 15. The date moved by one week."
    )
    evidence = {
        "passages": [
            {
                "passage_id": str(passage_id),
                "content": content,
                "content_hash": sha256(content.encode()).hexdigest(),
                "active_version": True,
            }
        ],
        "decision_fields": [],
    }
    prompt = f"<evidence>{json.dumps(evidence)}</evidence>"

    result = await SmokeGenerationProvider().generate(
        prompt, GeneratedAnswerCandidate
    )

    assert result.confidence == "high"
    assert result.claims[0].central is True
    assert result.claims[0].passage_ids == [passage_id]
    assert result.citations[0].passage_id == passage_id
    assert result.citations[0].quote in content


@pytest.mark.asyncio
async def test_smoke_answer_cites_both_beta_decisions_for_conflict_verification() -> None:
    later_id = uuid4()
    earlier_id = uuid4()
    later = (
        "This accepted revision supersedes the June 12 proposal to begin the "
        "internal beta on July 15."
    )
    earlier = (
        "Start an employee-only authentication beta on July 15, 2026, using the "
        "existing OpenID Connect provider."
    )
    evidence = {
        "passages": [
            {
                "passage_id": str(later_id),
                "content": later,
                "content_hash": sha256(later.encode()).hexdigest(),
                "active_version": True,
            },
            {
                "passage_id": str(earlier_id),
                "content": earlier,
                "content_hash": sha256(earlier.encode()).hexdigest(),
                "active_version": True,
            },
        ],
        "decision_fields": [
            {"passage_id": str(later_id)},
            {"passage_id": str(earlier_id)},
        ],
    }

    result = await SmokeGenerationProvider().generate(
        f"<evidence>{json.dumps(evidence)}</evidence>",
        GeneratedAnswerCandidate,
    )

    assert {citation.passage_id for citation in result.citations} == {
        later_id,
        earlier_id,
    }


def test_smoke_app_overrides_only_centralized_provider_dependency() -> None:
    from tests.smoke_app import app
    from decision_assistant.providers.factory import get_provider_bundle_factory

    assert set(app.dependency_overrides) == {get_provider_bundle_factory}
