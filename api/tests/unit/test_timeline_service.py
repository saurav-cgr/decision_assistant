from datetime import date, datetime, timezone
from importlib import import_module
from typing import Any
from uuid import UUID


def candidate(
    decision_id: str,
    *,
    effective_date: date | None,
    document_date: date | None,
    created_at: datetime,
) -> Any:
    timeline_service = import_module("decision_assistant.timelines.service")
    return timeline_service.TimelineSortCandidate(
        decision_id=UUID(decision_id),
        effective_date=effective_date,
        document_date=document_date,
        created_at=created_at,
    )


def test_timeline_order_interleaves_effective_and_fallback_dates() -> None:
    timeline_service = import_module("decision_assistant.timelines.service")
    created = datetime(2026, 7, 1, tzinfo=timezone.utc)
    known_early = candidate(
        "10000000-0000-0000-0000-000000000001",
        effective_date=date(2026, 7, 10),
        document_date=date(2026, 8, 1),
        created_at=created,
    )
    fallback_middle = candidate(
        "10000000-0000-0000-0000-000000000002",
        effective_date=None,
        document_date=date(2026, 7, 15),
        created_at=created,
    )
    known_late = candidate(
        "10000000-0000-0000-0000-000000000003",
        effective_date=date(2026, 7, 20),
        document_date=date(2026, 6, 1),
        created_at=created,
    )

    ordered = timeline_service.order_timeline_candidates(
        [known_late, fallback_middle, known_early]
    )

    assert [item.decision_id for item in ordered] == [
        known_early.decision_id,
        fallback_middle.decision_id,
        known_late.decision_id,
    ]
    assert fallback_middle.sort_date == date(2026, 7, 15)
    assert fallback_middle.date_is_fallback is True
    assert known_early.sort_date == date(2026, 7, 10)
    assert known_early.date_is_fallback is False


def test_timeline_places_missing_dates_last_then_orders_by_created_at() -> None:
    timeline_service = import_module("decision_assistant.timelines.service")
    dated = candidate(
        "20000000-0000-0000-0000-000000000001",
        effective_date=None,
        document_date=date(2026, 12, 31),
        created_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
    )
    missing_early = candidate(
        "20000000-0000-0000-0000-000000000002",
        effective_date=None,
        document_date=None,
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    missing_late = candidate(
        "20000000-0000-0000-0000-000000000003",
        effective_date=None,
        document_date=None,
        created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )

    ordered = timeline_service.order_timeline_candidates(
        [missing_late, dated, missing_early]
    )

    assert [item.decision_id for item in ordered] == [
        dated.decision_id,
        missing_early.decision_id,
        missing_late.decision_id,
    ]
    assert missing_early.sort_date is None
    assert missing_early.date_is_fallback is False
