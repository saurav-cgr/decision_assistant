"""Reingest a reproducible source corpus through the HTTP API.

Usage:
    python scripts/ingest_corpus.py \
        --source-directory sample_data/atlas \
        --workspace-name Atlas

The script creates/activates the target workspace, uploads every supported
source file in stable filename order, polls each ingestion job, and prints a
machine-readable JSON summary. It fails nonzero if any file is rejected, fails,
or times out. It never reads old database rows or uploads to reconstruct
sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

API_ORIGIN = os.getenv("INGEST_API_ORIGIN", "http://localhost:8000").rstrip("/")
API_V1 = f"{API_ORIGIN}/api/v1"
POLL_INTERVAL_SECONDS = float(os.getenv("INGEST_POLL_INTERVAL_SECONDS", "2"))
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("INGEST_TIMEOUT_SECONDS", "600"))

SUPPORTED_SUFFIXES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


class IngestFailure(RuntimeError):
    pass


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected_statuses: set[int] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    allowed = expected_statuses or {200}
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            if response.status not in allowed:
                raise IngestFailure(
                    f"{method} {url} returned unexpected HTTP {response.status}"
                )
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise IngestFailure(
            f"{method} {url} failed with HTTP {exc.code}: {details}"
        ) from exc
    except URLError as exc:
        raise IngestFailure(f"{method} {url} failed: {exc.reason}") from exc

    if not body:
        return {}
    try:
        return json.loads(body)
    except ValueError as exc:
        raise IngestFailure(f"{method} {url} returned non-JSON response") from exc


def _find_or_create_workspace(name: str) -> str:
    listing = _request_json(f"{API_V1}/workspaces")
    items = listing.get("items") or []
    for item in items:
        if item.get("name") == name:
            workspace_id = str(item["id"])
            _request_json(
                f"{API_V1}/workspaces/{workspace_id}/activate",
                method="POST",
                expected_statuses={200},
            )
            return workspace_id
    created = _request_json(
        f"{API_V1}/workspaces",
        method="POST",
        payload={"name": name},
        expected_statuses={201},
    )
    workspace_id = str(created["id"])
    _request_json(
        f"{API_V1}/workspaces/{workspace_id}/activate",
        method="POST",
        expected_statuses={200},
    )
    return workspace_id


def _upload(workspace_id: str, path: Path) -> dict[str, Any]:
    boundary = "----ingest-boundary"
    content_type = SUPPORTED_SUFFIXES[path.suffix.lower()]
    raw = path.read_bytes()
    fields = [
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
            f'filename="{path.name}"\r\nContent-Type: {content_type}\r\n\r\n'
        ).encode("utf-8")
        + raw
        + b"\r\n"
    ]
    body = b"".join(fields) + f"--{boundary}--\r\n".encode("utf-8")
    return _request_json(
        f"{API_V1}/workspaces/{workspace_id}/documents/upload",
        method="POST",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        expected_statuses={202},
    )


def _wait_for_active(workspace_id: str, document_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    detail_url = f"{API_V1}/workspaces/{workspace_id}/documents/{document_id}"
    list_url = f"{API_V1}/workspaces/{workspace_id}/documents"
    while time.monotonic() < deadline:
        detail = _request_json(detail_url)
        active = detail.get("active_version")
        if isinstance(active, dict) and active.get("state") == "active":
            return detail
        listing = _request_json(list_url)
        for item in listing.get("items") or []:
            if str(item.get("id")) == document_id and item.get("status") == "failed":
                error = item.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                raise IngestFailure(
                    f"Document {document_id} ingestion failed: {code or 'ingestion_failed'}"
                )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise IngestFailure(f"Document {document_id} did not become active before timeout")


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest(
    *,
    source_directory: Path,
    workspace_name: str,
    timeout: float,
    extensions: set[str],
) -> list[dict[str, Any]]:
    if not source_directory.is_dir():
        raise IngestFailure(f"Source directory not found: {source_directory}")
    paths = sorted(
        path
        for path in source_directory.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions
    )
    if not paths:
        raise IngestFailure(f"No supported source files under {source_directory}")

    workspace_id = _find_or_create_workspace(workspace_name)
    summary: list[dict[str, Any]] = []
    for path in paths:
        result = _upload(workspace_id, path)
        upload = result["results"][0]
        if upload.get("status") != "accepted":
            raise IngestFailure(f"Upload rejected for {path.name}: {upload}")
        document_id = str(upload["document_id"])
        detail = _wait_for_active(workspace_id, document_id, timeout)
        active = detail["active_version"]
        passages = detail.get("passages") or []
        summary.append(
            {
                "filename": path.name,
                "checksum": _checksum(path),
                "document_id": document_id,
                "active_version_id": str(active["id"]),
                "passage_count": len(passages),
                "chunking_profile": active.get("chunking_profile"),
            }
        )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reingest a reproducible corpus")
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--workspace-name", required=True)
    parser.add_argument("--api-origin", default=API_ORIGIN)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--extension",
        action="append",
        default=[],
        choices=sorted(SUPPORTED_SUFFIXES),
        help="Supported file extension to ingest (repeatable)",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    global API_ORIGIN, API_V1
    API_ORIGIN = args.api_origin.rstrip("/")
    API_V1 = f"{API_ORIGIN}/api/v1"
    extensions = set(args.extension) or set(SUPPORTED_SUFFIXES)
    summary = ingest(
        source_directory=args.source_directory,
        workspace_name=args.workspace_name,
        timeout=args.timeout,
        extensions=extensions,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
