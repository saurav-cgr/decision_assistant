"""Docker-network smoke test for the Decision Assistant MVP."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


API_ORIGIN = os.getenv("SMOKE_API_ORIGIN", "http://api:8000").rstrip("/")
API_V1 = f"{API_ORIGIN}/api/v1"
HEALTH_URL = f"{API_ORIGIN}/health"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = PROJECT_ROOT / "sample_data" / "atlas"
POLL_INTERVAL_SECONDS = float(os.getenv("SMOKE_POLL_INTERVAL_SECONDS", "2"))
TIMEOUT_SECONDS = float(os.getenv("SMOKE_TIMEOUT_SECONDS", "600"))
QUESTION = (
    "Was the June internal authentication beta proposal later changed, "
    "and what decision superseded it?"
)
MEDIA_TYPES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


class SmokeFailure(RuntimeError):
    """Raised when an end-to-end smoke invariant fails."""


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected_statuses: set[int] | None = None,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    allowed = expected_statuses or {200}
    try:
        with urlopen(request, timeout=30) as response:
            response_body = response.read()
            if response.status not in allowed:
                raise SmokeFailure(
                    f"{method} {url} returned unexpected HTTP {response.status}"
                )
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(
            f"{method} {url} failed with HTTP {exc.code}: {details}"
        ) from exc
    except URLError as exc:
        raise SmokeFailure(f"{method} {url} failed: {exc.reason}") from exc

    if not response_body:
        return {}
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{method} {url} returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise SmokeFailure(f"{method} {url} returned a non-object JSON response")
    return parsed


def _multipart_files(paths: list[Path]) -> tuple[bytes, str]:
    boundary = f"decision-assistant-{uuid4().hex}"
    chunks: list[bytes] = []
    for path in paths:
        if not path.is_file():
            raise SmokeFailure(f"Smoke fixture is missing: {path}")
        media_type = MEDIA_TYPES.get(path.suffix.casefold())
        if media_type is None:
            raise SmokeFailure(f"Smoke fixture has unsupported extension: {path}")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    'Content-Disposition: form-data; name="files"; '
                    f'filename="{path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {media_type}\r\n\r\n".encode("ascii"),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), boundary


def _upload_documents(paths: list[Path]) -> dict[str, str]:
    body, boundary = _multipart_files(paths)
    response = _request_json(
        f"{API_V1}/documents/upload",
        method="POST",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        expected_statuses={202},
    )
    results = response.get("results")
    if not isinstance(results, list) or len(results) != len(paths):
        raise SmokeFailure("Upload response did not contain every fixture")

    document_ids: dict[str, str] = {}
    for result in results:
        if not isinstance(result, dict):
            raise SmokeFailure("Upload response contained an invalid result")
        filename = result.get("filename")
        document_id = result.get("document_id")
        if result.get("status") != "accepted" or not filename or not document_id:
            raise SmokeFailure(f"Fixture upload was rejected: {result}")
        document_ids[str(filename)] = str(document_id)
    return document_ids


def _wait_for_active_document(document_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        detail = _request_json(f"{API_V1}/documents/{document_id}")
        active_version = detail.get("active_version")
        if isinstance(active_version, dict) and active_version.get("state") == "active":
            passages = detail.get("passages")
            if not isinstance(passages, list) or not passages:
                raise SmokeFailure(f"Indexed document {document_id} has no passages")
            return detail
        listing = _request_json(f"{API_V1}/documents")
        items = listing.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict) or str(item.get("id")) != document_id:
                    continue
                if item.get("status") == "failed":
                    error = item.get("error")
                    code = error.get("code") if isinstance(error, dict) else None
                    safe_code = code if isinstance(code, str) else "ingestion_failed"
                    raise SmokeFailure(
                        f"Document {document_id} ingestion failed: {safe_code}"
                    )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise SmokeFailure(f"Document {document_id} did not become active before timeout")


def _decision_for_version(
    decisions: list[dict[str, Any]],
    *,
    version_id: str,
    required_terms: tuple[str, ...],
) -> dict[str, Any]:
    candidates = [
        decision
        for decision in decisions
        if str(decision.get("document_version_id")) == version_id
    ]
    ranked = sorted(
        candidates,
        key=lambda decision: sum(
            term in (
                f"{decision.get('statement', '')} {decision.get('topic', '')}"
            ).casefold()
            for term in required_terms
        ),
        reverse=True,
    )
    if not ranked:
        raise SmokeFailure(f"No decision found for document version {version_id}")
    searchable = f"{ranked[0].get('statement', '')} {ranked[0].get('topic', '')}".casefold()
    if not all(term in searchable for term in required_terms):
        raise SmokeFailure(
            f"Expected decision terms {required_terms} were not extracted from "
            f"document version {version_id}"
        )
    return ranked[0]


def _assert_timeline(
    timeline: dict[str, Any],
    *,
    earlier_id: str,
    later_id: str,
) -> None:
    entries = timeline.get("entries")
    if not isinstance(entries, list):
        raise SmokeFailure("Timeline response has no entries")
    earlier = next(
        (entry for entry in entries if str(entry.get("decision_id")) == earlier_id),
        None,
    )
    later = next(
        (entry for entry in entries if str(entry.get("decision_id")) == later_id),
        None,
    )
    if earlier is None or later is None:
        raise SmokeFailure("Timeline omitted a related authentication decision")
    if earlier.get("display_status") != "superseded":
        raise SmokeFailure("Timeline did not project the earlier proposal as superseded")
    relationships = later.get("relationships")
    confirmed = (
        isinstance(relationships, list)
        and any(
            str(item.get("source_decision_id")) == later_id
            and str(item.get("target_decision_id")) == earlier_id
            and item.get("relation_type") == "supersedes"
            and item.get("authority") == "user_confirmed"
            for item in relationships
            if isinstance(item, dict)
        )
    )
    if not confirmed:
        raise SmokeFailure("Timeline omitted the confirmed supersedes relationship")
    if not earlier.get("evidence") or not later.get("evidence"):
        raise SmokeFailure("Timeline entries are missing source evidence")


def run_smoke() -> None:
    health = _request_json(HEALTH_URL)
    if health.get("status") != "ok":
        raise SmokeFailure("Unversioned health endpoint is not ready")

    # Resolve the active workspace (create one if the corpus is empty) and scope
    # every project-data request below /api/v1/workspaces/{id}/...
    global API_V1
    workspaces = _request_json(f"{API_V1}/workspaces")
    items = workspaces.get("items") or []
    active = next((w for w in items if w.get("is_active")), None)
    if active is None:
        created = _request_json(
            f"{API_V1}/workspaces",
            method="POST",
            payload={"name": "Smoke Workspace"},
            expected_statuses={201},
        )
        workspace_id = created["id"]
    else:
        workspace_id = active["id"]
    API_V1 = f"{API_V1}/workspaces/{workspace_id}"

    fixture_paths = [
        SAMPLE_ROOT / "02-architecture-sync.md",
        SAMPLE_ROOT / "03-auth-rollout.md",
    ]
    details: dict[str, dict[str, Any]] = {}
    for fixture_path in fixture_paths:
        document_ids = _upload_documents([fixture_path])
        details[fixture_path.name] = _wait_for_active_document(
            document_ids[fixture_path.name]
        )

    answer = _request_json(
        f"{API_V1}/questions",
        method="POST",
        payload={"question": QUESTION},
    )
    citations = answer.get("citations")
    if not isinstance(citations, list) or not citations:
        raise SmokeFailure("Question answer has no verifiable citation")
    if answer.get("state") == "abstained":
        raise SmokeFailure("Question unexpectedly abstained despite indexed evidence")

    decision_response = _request_json(f"{API_V1}/decisions")
    decisions = decision_response.get("items")
    if not isinstance(decisions, list):
        raise SmokeFailure("Decision list response has no items")
    earlier_version = str(
        details["02-architecture-sync.md"]["active_version"]["id"]
    )
    later_version = str(details["03-auth-rollout.md"]["active_version"]["id"])
    earlier = _decision_for_version(
        decisions,
        version_id=earlier_version,
        required_terms=("authentication", "beta"),
    )
    later = _decision_for_version(
        decisions,
        version_id=later_version,
        required_terms=("authentication", "beta"),
    )
    earlier_id = str(earlier["id"])
    later_id = str(later["id"])

    relation = _request_json(
        f"{API_V1}/decisions/{later_id}/relations",
        method="POST",
        payload={
            "target_decision_id": earlier_id,
            "relation_type": "supersedes",
            "rationale": (
                "The accepted July 22 internal-beta decision supersedes the "
                "June proposal for July 15."
            ),
        },
        expected_statuses={201},
    )
    if relation.get("authority") != "user_confirmed":
        raise SmokeFailure("Created relation is not authoritative")

    query = urlencode({"topic": "authentication"})
    timeline = _request_json(f"{API_V1}/timelines?{query}")
    _assert_timeline(timeline, earlier_id=earlier_id, later_id=later_id)

    print("SMOKE PASS: upload -> index -> ask -> citation -> timeline")


def main() -> int:
    try:
        run_smoke()
    except SmokeFailure as exc:
        print(f"SMOKE FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
