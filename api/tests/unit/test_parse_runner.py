"""DB60 (checker V139): the PDF parse must run somewhere the timeout can kill.

The break the checker found was not a wrong error code — it was that the timed-out parse *kept
running*, holding about 5 cores and 2 GiB for minutes until enough of them OOM-killed the API. So the
assertions here are about the process, not the message: the parse runs in a child, a timeout kills
that child, and the parse slot is released either way.

These tests use a real PDF fixture on purpose. A patched parser cannot cross a process boundary, and a
parse that never actually loads Docling cannot prove that its memory is reclaimed.
"""

import multiprocessing
import threading
from pathlib import Path

import pytest

from decision_assistant.ingestion import parse_runner as parse_runner_module
from decision_assistant.ingestion.parse_runner import (
    ParseTimeoutError,
    parse_slots,
    run_parse_in_subprocess,
)
from decision_assistant.ingestion.parsers import DocumentParseError, ParsedDocument

#: A real two-page digital PDF; small enough to parse in a few seconds, heavy enough that a 10 ms
#: budget is always exceeded (see the timeout test).
PDF_FIXTURE = Path("tests/fixtures/pdf/digital-english.pdf")

#: Generous, because this is the budget for a *successful* parse on a slow machine.
PARSE_BUDGET_SECONDS = 180.0


def test_a_real_pdf_parses_in_a_child_process_and_leaves_nothing_behind() -> None:
    parsed = run_parse_in_subprocess(
        PDF_FIXTURE,
        timeout_seconds=PARSE_BUDGET_SECONDS,
        concurrency_limit=1,
    )

    assert isinstance(parsed, ParsedDocument)
    assert parsed.source_path == PDF_FIXTURE
    assert parsed.blocks
    # A child that outlived its call would show up here (and would keep holding its converter).
    assert _live_parse_children() == []


def test_a_timed_out_parse_is_killed_and_frees_its_slot() -> None:
    with pytest.raises(ParseTimeoutError):
        # Docling cannot load its models in 10 ms, so this always times out — the test does not
        # depend on Docling's speed to be slow, only on it not being instant.
        run_parse_in_subprocess(
            PDF_FIXTURE,
            timeout_seconds=0.01,
            concurrency_limit=1,
        )

    assert _live_parse_children() == []
    # The slot must be released on the timeout path, or one slow PDF would wedge every later parse.
    slots = parse_slots(1)
    assert slots.acquire(blocking=False) is True
    slots.release()


def test_the_parse_slot_pool_bounds_concurrent_parses() -> None:
    slots = parse_slots(1)
    assert slots.acquire(timeout=5) is True
    outcome: dict[str, object] = {}

    def parse() -> None:
        try:
            outcome["parsed"] = run_parse_in_subprocess(
                PDF_FIXTURE,
                timeout_seconds=PARSE_BUDGET_SECONDS,
                concurrency_limit=1,
            )
        except BaseException as error:  # noqa: BLE001 - surfaced by the assertions below
            outcome["error"] = error

    worker = threading.Thread(target=parse)
    worker.start()
    try:
        worker.join(timeout=0.5)
        # Still waiting for the slot, so it has not been handed to Docling yet.
        assert worker.is_alive()
        assert outcome == {}
    finally:
        slots.release()

    worker.join(timeout=PARSE_BUDGET_SECONDS)
    assert not worker.is_alive()
    assert isinstance(outcome.get("parsed"), ParsedDocument)


def test_the_parse_slot_pool_is_reused_for_the_same_limit() -> None:
    assert parse_slots(1) is parse_slots(1)
    assert parse_slots(3) is not parse_slots(1)
    # Restore the production-sized pool for any later test in this session.
    assert parse_slots(1) is parse_slots(1)


def test_a_child_parse_error_keeps_its_sanitized_code(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a PDF at all")

    with pytest.raises(DocumentParseError) as error:
        run_parse_in_subprocess(
            broken,
            timeout_seconds=PARSE_BUDGET_SECONDS,
            concurrency_limit=1,
        )

    assert error.value.code == "pdf_parse_failed"
    assert error.value.message == "PDF could not be parsed"
    assert error.value.retryable is False


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        (("error", "pdf_ocr_failed", "PDF OCR failed"), "pdf_ocr_failed"),
        (("error", "pdf_parse_failed", "PDF could not be parsed"), "pdf_parse_failed"),
        # Anything unexpected in the pipe is sanitized rather than echoed to an API consumer.
        (("error", None, None), "pdf_parse_failed"),
        ("not-a-tuple", "pdf_parse_failed"),
        ((), "pdf_parse_failed"),
        (("ok", "not a parsed document"), "pdf_parse_failed"),
    ],
)
def test_unexpected_child_messages_are_sanitized(
    message: object, expected_code: str
) -> None:
    from decision_assistant.ingestion.parse_runner import _read_message

    with pytest.raises(DocumentParseError) as error:
        _read_message(message)

    assert error.value.code == expected_code


@pytest.mark.parametrize(
    ("timeout_seconds", "concurrency_limit"),
    [(0, 1), (-1, 1), (1, 0), (1, -2)],
)
def test_a_nonsensical_budget_is_rejected(
    timeout_seconds: float, concurrency_limit: int
) -> None:
    with pytest.raises(ValueError):
        run_parse_in_subprocess(
            PDF_FIXTURE,
            timeout_seconds=timeout_seconds,
            concurrency_limit=concurrency_limit,
        )


def test_a_parse_that_cannot_get_a_slot_gives_up_instead_of_waiting_forever() -> None:
    # DB63: without a cap this call waited for as long as the backlog took — a 2-page PDF sat about six
    # minutes behind 13 slow ones. The cap is injectable precisely so proving it does not take minutes.
    slots = parse_slots(1)
    assert slots.acquire(timeout=5) is True
    try:
        with pytest.raises(ParseTimeoutError):
            run_parse_in_subprocess(
                PDF_FIXTURE,
                timeout_seconds=PARSE_BUDGET_SECONDS,
                concurrency_limit=1,
                queue_wait_seconds=0.05,
            )
    finally:
        slots.release()

    assert _live_parse_children() == []


def test_the_child_watchdog_notices_a_dead_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    # DB63: `daemon=True` only fires on a clean parent exit, so the child checks the parent itself. A
    # reparented child sees a different ppid and exits before it can become an orphan parse.
    monkeypatch.setattr(parse_runner_module.os, "getppid", lambda: 4242)

    assert parse_runner_module._parent_is_gone(4242) is False
    assert parse_runner_module._parent_is_gone(1111) is True


def _live_parse_children() -> list[multiprocessing.process.BaseProcess]:
    return [
        child
        for child in multiprocessing.active_children()
        if child.name == "docling-parse"
    ]
