"""Run a document parse in a child process that the timeout can actually kill.

`asyncio.wait_for(asyncio.to_thread(...))` bounds how long the *caller* waits, but a thread cannot be
cancelled: a timed-out Docling parse kept its worker thread — about 5 cores and 2 GiB in the
checker's run — alive for minutes after its job had already been marked failed. Fourteen of those,
plus one ordinary upload, OOM-killed the API and it stayed down until a manual restart, which is
exactly what SC-009/FR-022 forbid (checker V139, loop debt DB60).

A child process can be killed, so the timeout becomes a real bound: the CPU and the memory go away
with the process. Two costs are accepted deliberately:

* the child re-imports Docling and builds its own `DocumentConverter` per parse. That is a few
  seconds of model loading per PDF, paid so that a kill discards the half-initialised converter
  instead of leaving one behind.
* the slot pool below is process-wide, which is the whole API today (`uvicorn --workers 1`). If the
  API ever runs more than one worker this limit becomes per worker, and the effective bound multiplies.

This module holds no parser logic and no product behaviour: it only decides *where* a parse runs and
when it is abandoned. `parse_document` and its types stay frozen.

Two residuals from DB60 are closed here (DB63): the slot wait is bounded (`_QUEUE_WAIT_MULTIPLE`
budgets, floored at `_QUEUE_WAIT_FLOOR_SECONDS`) so a queued parse cannot wait behind an unbounded
backlog, and the child watches its parent so a host run cannot leave an orphan parse behind. The
remaining costs are accepted: a spawn re-loads Docling's models (about four seconds per PDF), and a
kill skips Docling's own cleanup.
"""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from multiprocessing.connection import Connection
from pathlib import Path

from decision_assistant.ingestion.parsers import (
    DocumentParseError,
    ParsedDocument,
    parse_document,
)

#: Child process name, so a leaked process is identifiable and tests can look for it.
PROCESS_NAME = "docling-parse"

#: How long to wait for a child that has already sent its result (or been killed) to be reaped.
_JOIN_TIMEOUT_SECONDS = 10.0

#: DB63: how long a parse may wait for a slot before it gives up. Deliberately much larger than the
#: parse budget itself (20x, with a ten-minute floor), because the cap exists only to turn an
#: unbounded wait into a bounded failure — not to shorten normal queueing. A document queued behind a
#: backlog still gets parsed; a document queued behind an unbounded one fails with the same
#: `pdf_parse_timeout` code rather than holding an executor thread forever. Lower the queue depth
#: with `PDF_PARSE_CONCURRENCY`, not with this.
_QUEUE_WAIT_FLOOR_SECONDS = 600.0
_QUEUE_WAIT_MULTIPLE = 20.0

#: How often the child checks whether the process that started it is still alive (DB63).
_WATCHDOG_INTERVAL_SECONDS = 1.0

_slots_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
_slots_size: int | None = None


class ParseTimeoutError(Exception):
    """The child parse exceeded its budget and was killed.

    Deliberately not an `ApplicationError`: mapping it to a sanitized error code is the caller's
    decision (see `ingestion.service._parse_for_ingestion`), and this exception carries no detail
    that is safe to show an API consumer.
    """


def parse_slots(limit: int) -> threading.BoundedSemaphore:
    """The process-wide pool of parse slots, one semaphore per distinct `limit`.

    Public because the concurrency bound is worth asserting directly, and because the runner is the
    only holder: `limit` is 1 by default, so a second PDF waits for the first parse to finish or to be
    killed rather than starting a second Docling child beside it (DB60).
    """
    global _slots, _slots_size
    with _slots_lock:
        if _slots is None or _slots_size != limit:
            _slots = threading.BoundedSemaphore(limit)
            _slots_size = limit
        return _slots


def run_parse_in_subprocess(
    source_path: Path,
    *,
    timeout_seconds: float,
    concurrency_limit: int,
    queue_wait_seconds: float | None = None,
) -> ParsedDocument:
    """Parse `source_path` in a child process, killing it if `timeout_seconds` elapses.

    Blocks the calling thread — callers on the event loop must wrap it in `asyncio.to_thread`. Raises
    `ParseTimeoutError` when the child was killed or when the slot wait elapsed first, and
    `DocumentParseError` when the child reported one.

    `queue_wait_seconds` defaults to `_QUEUE_WAIT_MULTIPLE * timeout_seconds`, floored at
    `_QUEUE_WAIT_FLOOR_SECONDS` (DB63): without a cap, a parse queued behind a backlog waited for as
    long as the backlog took. Injectable so a test can prove the cap fires without waiting minutes.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if concurrency_limit <= 0:
        raise ValueError("concurrency_limit must be positive")
    wait_budget = queue_wait_seconds
    if wait_budget is None:
        wait_budget = max(_QUEUE_WAIT_FLOOR_SECONDS, _QUEUE_WAIT_MULTIPLE * timeout_seconds)
    slot = parse_slots(concurrency_limit)
    if not slot.acquire(timeout=wait_budget):
        raise ParseTimeoutError(
            f"waited longer than {wait_budget:g}s for a parse slot and gave up"
        )
    try:
        return _run_child(source_path, timeout_seconds)
    finally:
        slot.release()


def _run_child(source_path: Path, timeout_seconds: float) -> ParsedDocument:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_in_child,
        args=(str(source_path), child, os.getpid()),
        name=PROCESS_NAME,
        daemon=True,
    )
    try:
        process.start()
    except BaseException:
        parent.close()
        child.close()
        raise

    # The parent's copy of the write end must be closed, or `poll` never sees EOF when the child dies
    # without sending (a killed child, an OOM-killed child, a crash before the send).
    child.close()
    try:
        if not parent.poll(timeout_seconds):
            raise ParseTimeoutError(
                f"parse did not finish within {timeout_seconds:g}s and was killed"
            )
        try:
            message = parent.recv()
        except EOFError as exc:
            raise DocumentParseError(
                "pdf_parse_failed", "PDF could not be parsed"
            ) from exc
    finally:
        parent.close()
        _retire(process)

    return _read_message(message)


def _read_message(message: object) -> ParsedDocument:
    if not isinstance(message, tuple) or not message:
        raise DocumentParseError("pdf_parse_failed", "PDF could not be parsed")
    status, *payload = message
    if status == "ok" and len(payload) == 1 and isinstance(payload[0], ParsedDocument):
        return payload[0]
    if status == "error" and len(payload) == 2:
        code, detail = payload
        return _raise_parse_error(code, detail)
    raise DocumentParseError("pdf_parse_failed", "PDF could not be parsed")


def _raise_parse_error(code: object, detail: object) -> ParsedDocument:
    # `DocumentParseError` needs one string code and one sanitized message; anything else in the pipe
    # is treated as an unexpected child failure rather than echoed to the API consumer.
    if isinstance(code, str) and isinstance(detail, str) and code and detail:
        raise DocumentParseError(code, detail)
    raise DocumentParseError("pdf_parse_failed", "PDF could not be parsed")


def _retire(process: multiprocessing.process.BaseProcess) -> None:
    """Kill a live child and reap it, so no parse outlives the call that started it."""
    if process.is_alive():
        process.kill()
    process.join(_JOIN_TIMEOUT_SECONDS)


def _parent_is_gone(parent_pid: int) -> bool:
    """True when this process has been reparented, i.e. the process that started it exited."""
    return os.getppid() != parent_pid


def _parse_in_child(source_path: str, connection: Connection, parent_pid: int) -> None:
    """Child entry point: parse, then send either the result or a sanitized (code, message) pair."""
    # DB63: under Compose the container's namespace teardown kills this child when the API dies, but
    # a host run can leave an orphan parsing with no one left to kill it. `daemon=True` only covers a
    # clean parent exit, so watch the parent explicitly.
    watchdog = threading.Thread(
        target=_watch_parent,
        args=(parent_pid,),
        name=f"{PROCESS_NAME}-watchdog",
        daemon=True,
    )
    watchdog.start()
    try:
        parsed = parse_document(Path(source_path))
    except DocumentParseError as exc:
        connection.send(("error", exc.code, exc.message))
    except BaseException:  # noqa: BLE001 - the child's only job is to not leak a raw exception
        connection.send(("error", "pdf_parse_failed", "PDF could not be parsed"))
    else:
        connection.send(("ok", parsed))
    finally:
        connection.close()


def _watch_parent(parent_pid: int) -> None:
    """Exit hard as soon as the spawning process is gone, so no orphan parse survives it."""
    while True:
        if _parent_is_gone(parent_pid):
            os._exit(1)
        time.sleep(_WATCHDOG_INTERVAL_SECONDS)
