import importlib.util
import json
import sys
from pathlib import Path

import pytest

INGEST_SCRIPT_PATH = Path("/workspace/scripts/ingest_corpus.py")
COMPARE_SCRIPT_PATH = Path("/workspace/scripts/compare_chunk_profiles.py")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    _load_module("ingest_corpus", INGEST_SCRIPT_PATH)
    return _load_module("compare_chunk_profiles", COMPARE_SCRIPT_PATH)


def test_dry_run_plans_baseline_without_network(script) -> None:
    result = script.compare(
        preset="baseline",
        source_directory=Path("sample_data/atlas"),
        workspace_name="Atlas",
        api_origin="http://localhost:8000",
        dataset_version="atlas-v3",
        strategy="hybrid",
        timeout=60,
        dry_run=True,
    )

    assert result["status"] == "planned"
    assert result["preset"] == "baseline"
    assert result["profile"]["algorithm"] == "structural-token-v2"
    assert result["passage_count"] is None
    assert set(result["metrics"]) == set(script.METRIC_KEYS)
    assert all(value is None for value in result["metrics"].values())


@pytest.mark.parametrize("preset", ["baseline", "compact", "expanded"])
def test_result_serializes_exact_profile_and_metrics(script, preset: str) -> None:
    metrics = {
        "top_five_hit_rate": 0.8,
        "mean_reciprocal_rank": 0.6,
        "citation_structural_validity": 0.9,
        "citation_correctness": 0.7,
        "gold_citation_coverage": 0.5,
        "abstention_accuracy": 0.95,
        "facet_abstention_accuracy": 0.9,
        "answer_faithfulness": 0.85,
        "median_latency_ms": 1234.5,
        "p95_latency_ms": 2500.0,
        "question_failures": 2,
    }
    result = script.build_result(
        preset=preset,
        status="completed",
        passage_count=42,
        metrics=metrics,
    )

    assert result["status"] == "completed"
    assert result["preset"] == preset
    assert result["profile"] == script.CHUNKING_PROFILE_PRESETS[preset]
    assert result["passage_count"] == 42
    assert result["metrics"] == metrics

    # Only non-secret configuration and metrics are serialized.
    blob = json.dumps(result)
    assert "GEMINI_API_KEY" not in blob
    assert "AUTH_JWT_SECRET" not in blob
    assert "password" not in blob


def test_parser_rejects_unknown_preset(script) -> None:
    with pytest.raises(SystemExit):
        script._parser().parse_args(["--preset", "bogus"])


def test_parser_accepts_each_preset(script) -> None:
    for preset in ("baseline", "compact", "expanded"):
        args = script._parser().parse_args(["--preset", preset, "--dry-run"])
        assert args.preset == preset
        assert args.dry_run is True
