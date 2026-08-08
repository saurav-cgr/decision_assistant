from datetime import date
from pathlib import Path

import pytest

from decision_assistant.ingestion.metadata import MetadataExtractor
from decision_assistant.ingestion.parsers import parse_document
from decision_assistant.providers.fakes import FakeGenerationProvider


def write_markdown(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "meeting.md"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_front_matter_populates_metadata_without_model_call(
    tmp_path: Path,
) -> None:
    source = write_markdown(
        tmp_path,
        """---
title: Architecture Sync
date: 2026-07-15
participants: [Maya, Ravi]
source_type: meeting
project: Atlas
---

# Conflicting Heading

Authentication was postponed.
""",
    )
    provider = FakeGenerationProvider()

    metadata = await MetadataExtractor(provider).extract(parse_document(source))

    assert metadata.title == "Architecture Sync"
    assert metadata.document_date == date(2026, 7, 15)
    assert metadata.participants == ["Maya", "Ravi"]
    assert metadata.source_type == "meeting"
    assert metadata.project == "Atlas"
    assert provider.prompts == []


@pytest.mark.asyncio
async def test_heading_is_deterministic_and_model_fills_only_missing_fields(
    tmp_path: Path,
) -> None:
    source = write_markdown(
        tmp_path,
        "# Platform Review\n\nThe team reviewed authentication.\n",
    )
    provider = FakeGenerationProvider(
        [
            {
                "title": "Model must not replace heading",
                "document_date": "2026-07-18",
                "participants": ["Elena"],
                "source_type": "meeting",
                "project": "Atlas",
            }
        ]
    )

    metadata = await MetadataExtractor(provider).extract(parse_document(source))

    assert metadata.title == "Platform Review"
    assert metadata.document_date == date(2026, 7, 18)
    assert metadata.participants == ["Elena"]
    assert metadata.source_type == "meeting"
    assert metadata.project == "Atlas"
    assert len(provider.prompts) == 1


@pytest.mark.asyncio
async def test_absent_metadata_remains_unknown(tmp_path: Path) -> None:
    source = write_markdown(tmp_path, "A note without metadata.\n")
    provider = FakeGenerationProvider(
        [
            {
                "title": None,
                "document_date": None,
                "participants": [],
                "source_type": None,
                "project": None,
            }
        ]
    )

    metadata = await MetadataExtractor(provider).extract(parse_document(source))

    assert metadata.title is None
    assert metadata.document_date is None
    assert metadata.participants == []
    assert metadata.source_type is None
    assert metadata.project is None
