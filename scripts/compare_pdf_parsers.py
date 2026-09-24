"""Benchmark one PDF parser on a freshly reset and reingested Atlas corpus."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import ingest_corpus as ingest_module
from decision_assistant.ingestion.profiles import resolve_corpus_profile

DEFAULT_SOURCE_DIRECTORY = Path("/workspace/sample_data/atlas")
DEFAULT_DATASET_VERSION = "atlas-v3"
DEFAULT_WORKSPACE_NAME = "Atlas"
METRIC_KEYS = (
    "top_five_hit_rate",
    "citation_structural_validity",
    "citation_correctness",
    "abstention_accuracy",
    "conflict_rate",
)


def _run_evaluation(
    api_v1: str, workspace_id: str, dataset_version: str, timeout: float
) -> dict[str, Any]:
    created = ingest_module._request_json(
        f"{api_v1}/workspaces/{workspace_id}/evaluations/runs",
        method="POST",
        payload={"strategy": "hybrid", "dataset_version": dataset_version},
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
            raise RuntimeError(f"evaluation failed: {run.get('failure') or 'unknown'}")
        time.sleep(2)
    raise RuntimeError("evaluation timed out")


def _require_profile(summary: list[dict[str, Any]], expected: dict[str, Any]) -> None:
    actual = {json.dumps(item.get("chunking_profile"), sort_keys=True) for item in summary}
    if actual != {json.dumps(expected, sort_keys=True)}:
        raise RuntimeError("active corpus parser profile does not match --parser")


def compare(
    *,
    parser: str,
    source_directory: Path,
    workspace_name: str,
    api_origin: str,
    dataset_version: str,
    timeout: float,
) -> dict[str, Any]:
    ingest_module.API_ORIGIN = api_origin.rstrip("/")
    ingest_module.API_V1 = f"{ingest_module.API_ORIGIN}/api/v1"
    ingest_module._ensure_auth(timeout)
    expected_profile = resolve_corpus_profile("baseline", "passage_hybrid", parser)
    started = time.monotonic()
    workspace_id = ingest_module._find_or_create_workspace(workspace_name)
    summary = ingest_module.ingest(
        source_directory=source_directory,
        workspace_name=workspace_name,
        timeout=timeout,
        extensions=set(ingest_module.SUPPORTED_SUFFIXES),
    )
    _require_profile(summary, expected_profile)
    ingest_seconds = round(time.monotonic() - started, 3)
    run = _run_evaluation(
        ingest_module.API_V1, workspace_id, dataset_version, timeout
    )
    snapshots = run.get("corpus_snapshot") or []
    _require_profile(snapshots, expected_profile)
    metrics = dict(run.get("aggregate_metrics") or {})
    results = run.get("results") or []
    metrics["conflict_rate"] = round(
        sum(bool((item.get("generated_output") or {}).get("conflicts")) for item in results)
        / len(results),
        6,
    ) if results else 0.0
    return {
        "status": "completed",
        "parser": parser,
        "corpus_profile": expected_profile,
        "passage_count": sum(int(item.get("passage_count") or 0) for item in summary),
        "ingest_seconds": ingest_seconds,
        "metrics": {key: metrics.get(key) for key in METRIC_KEYS},
        "evaluation": {
            "run_id": str(run["id"]),
            "dataset_version": run["dataset_version"],
            "generation_profile": run["generation_profile"],
            "embedding_profile": run["embedding_profile"],
            "corpus_snapshot": snapshots,
            "aggregate_metrics": run["aggregate_metrics"],
            "result_count": len(results),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parser", required=True, choices=("pypdf", "docling"))
    parser.add_argument("--source-directory", type=Path, default=DEFAULT_SOURCE_DIRECTORY)
    parser.add_argument("--workspace-name", default=DEFAULT_WORKSPACE_NAME)
    parser.add_argument("--api-origin", default="http://api:8000")
    parser.add_argument("--dataset-version", default=DEFAULT_DATASET_VERSION)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    print(json.dumps(compare(**vars(args)), sort_keys=True))


if __name__ == "__main__":
    main()
