"""Compare a chunking-profile preset on a reproducible corpus.

Usage:
    python scripts/compare_chunk_profiles.py --preset baseline --dry-run
    python scripts/compare_chunk_profiles.py --preset expanded

The script reuses the existing corpus-ingestion script and the evaluation
service (no second retrieval implementation). It emits a machine-readable
result containing only non-secret configuration (the exact profile) and
metrics.

Operator procedure (run once per candidate preset):
  1. Reset PostgreSQL only (never ``docker compose down -v``): stop api/web,
     drop and recreate the database, migrate, and start api/web with
     ``CHUNKING_PROFILE_PRESET=<preset>``.
  2. Run this script with the same ``--preset`` against that freshly reset,
     reingested corpus.

Selection rule: the preset with the highest top-five retrieval hit rate becomes
the default; on a tie, retain ``baseline``.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import ingest_corpus as ingest_module
from decision_assistant.ingestion.profiles import (
    CHUNKING_PROFILE_PRESETS,
    resolve_chunking_profile,
)

POLL_INTERVAL_SECONDS = float(os.getenv("INGEST_POLL_INTERVAL_SECONDS", "2"))
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("INGEST_TIMEOUT_SECONDS", "600"))
DEFAULT_DATASET_VERSION = "atlas-v3"
DEFAULT_WORKSPACE_NAME = "Atlas"
DEFAULT_SOURCE_DIRECTORY = Path("sample_data/atlas")

# Metrics recorded for review; the selection metric is top-five hit rate.
METRIC_KEYS = (
    "top_five_hit_rate",
    "mean_reciprocal_rank",
    "citation_structural_validity",
    "citation_correctness",
    "gold_citation_coverage",
    "abstention_accuracy",
    "facet_abstention_accuracy",
    "answer_faithfulness",
    "median_latency_ms",
    "p95_latency_ms",
    "question_failures",
)


def build_result(
    *,
    preset: str,
    status: str,
    passage_count: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the machine-readable comparison result (non-secret only)."""
    return {
        "status": status,
        "preset": preset,
        "profile": resolve_chunking_profile(preset),
        "passage_count": passage_count,
        "metrics": {key: (metrics or {}).get(key) for key in METRIC_KEYS},
    }


def _extract_metrics(run: dict[str, Any]) -> dict[str, Any]:
    aggregate = run.get("aggregate_metrics") or {}
    return {key: aggregate.get(key) for key in METRIC_KEYS}


def _run_evaluation(
    api_v1: str,
    workspace_id: str,
    dataset_version: str,
    strategy: str,
    timeout: float,
) -> dict[str, Any]:
    created = ingest_module._request_json(
        f"{api_v1}/workspaces/{workspace_id}/evaluations/runs",
        method="POST",
        payload={
            "strategy": strategy,
            "dataset_version": dataset_version,
            "configuration": {},
        },
        expected_statuses={202},
        timeout=timeout,
    )
    run_id = str(created["id"])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = ingest_module._request_json(
            f"{api_v1}/workspaces/{workspace_id}/evaluations/runs/{run_id}",
            timeout=timeout,
        )
        status = run.get("status")
        if status == "completed":
            return run
        if status == "failed":
            raise RuntimeError(
                f"Evaluation run {run_id} failed: {run.get('failure') or 'unknown'}"
            )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"Evaluation run {run_id} did not complete before timeout")


def compare(
    *,
    preset: str,
    source_directory: Path,
    workspace_name: str,
    api_origin: str,
    dataset_version: str,
    strategy: str,
    timeout: float,
    dry_run: bool,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Run the comparison for one preset, or plan it with ``dry_run``."""
    if dry_run:
        return build_result(preset=preset, status="planned")

    api_origin = api_origin.rstrip("/")
    ingest_module.API_ORIGIN = api_origin
    ingest_module.API_V1 = f"{api_origin}/api/v1"
    if username is not None:
        ingest_module.AUTH_USERNAME = username
        ingest_module.AUTH_PASSWORD = password
    ingest_module._ensure_auth(timeout)

    workspace_id = ingest_module._find_or_create_workspace(workspace_name)
    summary = ingest_module.ingest(
        source_directory=source_directory,
        workspace_name=workspace_name,
        timeout=timeout,
        extensions=set(ingest_module.SUPPORTED_SUFFIXES),
    )
    passage_count = sum(int(item.get("passage_count") or 0) for item in summary)
    run = _run_evaluation(
        ingest_module.API_V1,
        workspace_id,
        dataset_version,
        strategy,
        timeout,
    )
    return build_result(
        preset=preset,
        status="completed",
        passage_count=passage_count,
        metrics=_extract_metrics(run),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare a chunking profile preset on a reproducible corpus"
    )
    parser.add_argument(
        "--preset",
        required=True,
        choices=sorted(CHUNKING_PROFILE_PRESETS),
        help="Chunking profile preset to benchmark",
    )
    parser.add_argument("--source-directory", type=Path, default=DEFAULT_SOURCE_DIRECTORY)
    parser.add_argument("--workspace-name", default=DEFAULT_WORKSPACE_NAME)
    parser.add_argument(
        "--api-origin",
        default=os.getenv("INGEST_API_ORIGIN", "http://localhost:8000"),
    )
    parser.add_argument("--dataset-version", default=DEFAULT_DATASET_VERSION)
    parser.add_argument(
        "--strategy",
        default="hybrid",
        choices=["hybrid", "semantic"],
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--username", default=os.getenv("INGEST_USERNAME"))
    parser.add_argument("--password", default=os.getenv("INGEST_PASSWORD"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate arguments and emit a planned result without touching the API",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = compare(
        preset=args.preset,
        source_directory=args.source_directory,
        workspace_name=args.workspace_name,
        api_origin=args.api_origin,
        dataset_version=args.dataset_version,
        strategy=args.strategy,
        timeout=args.timeout,
        dry_run=args.dry_run,
        username=args.username,
        password=args.password,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
