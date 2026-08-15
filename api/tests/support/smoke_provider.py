from __future__ import annotations

import json
import re
from hashlib import sha256
from html import unescape
from math import sqrt
from typing import Any
from uuid import UUID

from decision_assistant.answering.schemas import GeneratedAnswerCandidate
from decision_assistant.decisions.schemas import DecisionExtractionResponse
from decision_assistant.providers.base import (
    EmbeddingProfile,
    EmbeddingPurpose,
    GenerationProfile,
    GenerationRequest,
    ProviderOutputInvalid,
    ResponseModelT,
)

_PASSAGE_PATTERN = re.compile(
    r'<passage id="(?P<id>[^"]+)">\n(?P<content>.*?)\n</passage>',
    re.DOTALL,
)
_ARCHITECTURE_QUOTE = (
    "Start an employee-only authentication beta on July 15, 2026, using the "
    "existing OpenID Connect provider."
)
_ROLLOUT_QUOTE = (
    "Begin the employee-only authentication beta on July 22, 2026. Status: "
    "active. Priya Nair owns the rollout, and Jonah Reed owns security approval."
)
_SUPERSESSION_QUOTE = (
    "This accepted revision supersedes the June 12 proposal to begin the internal "
    "beta on July 15."
)


class SmokeEmbeddingProvider:
    """Deterministic 768-dimensional provider used only by Compose smoke tests."""

    profile = EmbeddingProfile(
        provider="smoke-fake",
        model="deterministic-sha256",
        dimension=768,
        adapter_config_version="smoke-v1",
    )

    async def embed(
        self,
        texts: list[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> list[list[float]]:
        del purpose
        if not texts:
            raise ValueError("Embedding input must contain at least one text")
        return [_vector(text) for text in texts]


class SmokeGenerationProvider:
    """Prompt-aware responses for two fixed Atlas Markdown smoke documents."""

    profile = GenerationProfile(
        provider="smoke-fake",
        model="atlas-two-document-fixture",
        api_version="test",
        sdk_version="test",
        temperature=0,
        schema_mode="json_schema",
        prompt_contract_version="smoke-v1",
    )
    max_prompt_characters = 100_000

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    async def generate(
        self,
        request: GenerationRequest,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        self.requests.append(request)
        prompt = request.user_content
        if response_model is DecisionExtractionResponse:
            payload = _decision_payload(prompt)
        elif response_model is GeneratedAnswerCandidate:
            payload = _answer_payload(prompt)
        else:
            raise ProviderOutputInvalid()
        return response_model.model_validate(payload)


def _decision_payload(prompt: str) -> dict[str, list[dict[str, Any]]]:
    decisions: list[dict[str, Any]] = []
    for match in _PASSAGE_PATTERN.finditer(prompt):
        passage_id = match.group("id")
        content = unescape(match.group("content"))
        if _ARCHITECTURE_QUOTE in content:
            decisions.append(
                {
                    "statement": _ARCHITECTURE_QUOTE,
                    "effective_date": "2026-07-15",
                    "owner": "Priya Nair",
                    "status": "proposed",
                    "reasons": ["Exercise authentication with limited exposure."],
                    "alternatives": ["Wait for the Q4 public rollout."],
                    "project": "Atlas",
                    "topic": "authentication",
                    "extraction_confidence": 1.0,
                    "evidence": {
                        "passage_id": passage_id,
                        "quote": _ARCHITECTURE_QUOTE,
                    },
                    "relation": None,
                }
            )
        if _ROLLOUT_QUOTE in content:
            decisions.append(
                {
                    "statement": _ROLLOUT_QUOTE,
                    "effective_date": "2026-07-22",
                    "owner": "Priya Nair",
                    "status": "active",
                    "reasons": [
                        "All six authorization audit events need integration testing."
                    ],
                    "alternatives": ["Keep July 15 and disable permission overrides."],
                    "project": "Atlas",
                    "topic": "authentication",
                    "extraction_confidence": 1.0,
                    "evidence": {
                        "passage_id": passage_id,
                        "quote": _ROLLOUT_QUOTE,
                    },
                    "relation": None,
                }
            )
    return {"decisions": decisions}


def _answer_payload(prompt: str) -> dict[str, Any]:
    match = re.search(r"<evidence>(.*?)</evidence>", prompt, re.DOTALL)
    if match is None:
        raise ProviderOutputInvalid()
    evidence = json.loads(match.group(1))
    citations: list[dict[str, Any]] = []
    later_passage_id: UUID | None = None
    for passage in evidence.get("passages", []):
        content = passage["content"]
        if _SUPERSESSION_QUOTE in content:
            quote = _SUPERSESSION_QUOTE
            later_passage_id = UUID(passage["passage_id"])
        elif _ARCHITECTURE_QUOTE in content:
            quote = _ARCHITECTURE_QUOTE
        else:
            continue
        passage_id = UUID(passage["passage_id"])
        citations.append(
            {
                "passage_id": str(passage_id),
                "quote": quote,
            }
        )
    if later_passage_id is None:
        raise ProviderOutputInvalid()
    return {
        "answer": (
            "Yes. The July 22 internal authentication beta decision superseded "
            "the June 12 July 15 proposal."
        ),
        "claims": [
            {
                "text": "The July revision superseded the June proposal.",
                "central": True,
                "passage_ids": [str(later_passage_id)],
                "explicit_entities": [],
                "explicit_dates": [],
            }
        ],
        "citations": citations,
        "conflicts": [],
        "unsupported_facets": [],
        "confidence": "high",
    }


def _vector(text: str) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < 768:
        digest = sha256(f"{counter}:{text.casefold()}".encode()).digest()
        values.extend((byte / 127.5) - 1.0 for byte in digest)
        counter += 1
    vector = values[:768]
    magnitude = sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]
