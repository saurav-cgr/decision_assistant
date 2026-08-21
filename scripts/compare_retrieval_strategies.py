"""Evaluate one retrieval-unit strategy on a freshly reingested corpus.

Usage:
    python scripts/compare_retrieval_strategies.py --strategy passage_hybrid --dry-run
    python scripts/compare_retrieval_strategies.py --strategy sentence_expanded

Run this once for each candidate. Before every non-dry run, reset PostgreSQL
only, configure ``RETRIEVAL_UNIT_STRATEGY`` to the selected strategy, and
reingest the same source directory. The runner deliberately never resets the
database: that destructive action stays explicit and operator-controlled.

The run pins top-five hybrid retrieval with reranking disabled. It records the
strategy, corpus profile, provider profiles returned by the evaluation API,
and the pre-agreed comparison metrics in non-secret JSON.
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
    DEFAULT_CHUNKING_PROFILE_PRESET,
    RETRIEVAL_UNIT_STRATEGIES,
    resolve_corpus_profile,
)

POLL_INTERVAL_SECONDS = float(os.getenv("INGEST_POLL_INTERVAL_SECONDS", "2"))
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("INGEST_TIMEOUT_SECONDS", "600"))
DEFAULT_DATASET_VERSION = "atlas-v3"
DEFAULT_WORKSPACE_NAME = "Atlas"
DEFAULT_SOURCE_DIRECTORY = Path("sample_data/atlas")

METRIC_KEYS = (
    "top_five_hit_rate",
    "mean_reciprocal_rank",
    "gold_citation_coverage",
    "median_latency_ms",
    "p95_latency_ms",
    "question_failures",
)


def build_result(
    *,
    strategy: str,
    status: str,
    passage_count: int | None = None,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-secret, machine-readable comparison record."""
    run = run or {}
    metrics = run.get("aggregate_metrics") or {}
    return {
        "status": status,
        "strategy": strategy,
        "corpus_profile": resolve_corpus_profile(
            DEFAULT_CHUNKING_PROFILE_PRESET, strategy
        ),
        "configuration": {"strategy": strategy, "top_k": 5, "rerank_enabled": False},
        "passage_count": passage_count,
        "generation_profile": run.get("generation_profile"),
        "embedding_profile": run.get("embedding_profile"),
        "metrics": {key: metrics.get(key) for key in METRIC_KEYS},
    }


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
            "configuration": {
                "strategy": strategy,
                "top_k": 5,
                "rerank_enabled": False,
            },
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
        if run.get("status") == "completed":
            return run
        if run.get("status") == "failed":
            raise RuntimeError(
                f"Evaluation run {run_id} failed: {run.get('failure') or 'unknown'}"
            )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"Evaluation run {run_id} did not complete before timeout")


def _require_matching_corpus(
    summary: list[dict[str, Any]], strategy: str
) -> None:
    expected = resolve_corpus_profile(DEFAULT_CHUNKING_PROFILE_PRESET, strategy)
    actual_profiles = {json.dumps(item.get("chunking_profile"), sort_keys=True) for item in summary}
    if actual_profiles != {json.dumps(expected, sort_keys=True)}:
        raise RuntimeError(
            "The reingested corpus profile does not match the selected strategy; "
            "reset PostgreSQL, restart with RETRIEVAL_UNIT_STRATEGY set to the "
            f"selected value, then reingest. Expected: {expected}"
        )


def compare(
    *,
    strategy: str,
    source_directory: Path,
    workspace_name: str,
    api_origin: str,
    dataset_version: str,
    timeout: float,
    dry_run: bool,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Ingest and evaluate one compatible corpus representation."""
    if dry_run:
        return build_result(strategy=strategy, status="planned")

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
    _require_matching_corpus(summary, strategy)
    run = _run_evaluation(
        ingest_module.API_V1, workspace_id, dataset_version, strategy, timeout
    )
    return build_result(
        strategy=strategy,
        status="completed",
        passage_count=sum(int(item.get("passage_count") or 0) for item in summary),
        run=run,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate one retrieval-unit strategy on a fresh corpus"
    )
    parser.add_argument("--strategy", required=True, choices=sorted(RETRIEVAL_UNIT_STRATEGIES))
    parser.add_argument("--source-directory", type=Path, default=DEFAULT_SOURCE_DIRECTORY)
    parser.add_argument("--workspace-name", default=DEFAULT_WORKSPACE_NAME)
    parser.add_argument("--api-origin", default=os.getenv("INGEST_API_ORIGIN", "http://localhost:8000"))
    parser.add_argument("--dataset-version", default=DEFAULT_DATASET_VERSION)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--username", default=os.getenv("INGEST_USERNAME"))
    parser.add_argument("--password", default=os.getenv("INGEST_PASSWORD"))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    print(
        json.dumps(
            compare(
                strategy=args.strategy,
                source_directory=args.source_directory,
                workspace_name=args.workspace_name,
                api_origin=args.api_origin,
                dataset_version=args.dataset_version,
                timeout=args.timeout,
                dry_run=args.dry_run,
                username=args.username,
                password=args.password,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
