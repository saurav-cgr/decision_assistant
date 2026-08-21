import importlib.util
import json
import sys
from pathlib import Path

import pytest

INGEST_SCRIPT_PATH = Path("/workspace/scripts/ingest_corpus.py")
SCRIPT_PATH = Path("/workspace/scripts/compare_retrieval_strategies.py")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    _load_module("ingest_corpus", INGEST_SCRIPT_PATH)
    return _load_module("compare_retrieval_strategies", SCRIPT_PATH)


@pytest.mark.parametrize(
    "strategy", ["passage_hybrid", "sentence_expanded", "parent_child_merged"]
)
def test_dry_run_plans_each_strategy_without_network(script, strategy: str) -> None:
    result = script.compare(
        strategy=strategy,
        source_directory=Path("sample_data/atlas"),
        workspace_name="Atlas",
        api_origin="http://localhost:8000",
        dataset_version="atlas-v3",
        timeout=60,
        dry_run=True,
    )

    assert result["status"] == "planned"
    assert result["strategy"] == strategy
    assert result["corpus_profile"]["retrieval_unit_strategy"] == strategy
    assert result["configuration"] == {
        "strategy": strategy,
        "top_k": 5,
        "rerank_enabled": False,
    }
    assert result["passage_count"] is None
    assert all(value is None for value in result["metrics"].values())


def test_result_includes_only_non_secret_profiles_and_metrics(script) -> None:
    result = script.build_result(
        strategy="sentence_expanded",
        status="completed",
        passage_count=42,
        run={
            "generation_profile": {"provider": "ollama", "model": "qwen2.5:3b"},
            "embedding_profile": {"provider": "ollama", "model": "nomic-embed-text"},
            "aggregate_metrics": {"top_five_hit_rate": 0.8, "median_latency_ms": 1234},
        },
    )

    assert result["metrics"]["top_five_hit_rate"] == 0.8
    assert result["metrics"]["median_latency_ms"] == 1234
    blob = json.dumps(result)
    assert "GEMINI_API_KEY" not in blob
    assert "AUTH_JWT_SECRET" not in blob
    assert "password" not in blob


def test_require_matching_corpus_rejects_wrong_representation(script) -> None:
    with pytest.raises(RuntimeError, match="does not match"):
        script._require_matching_corpus(
            [{"chunking_profile": {"retrieval_unit_strategy": "passage_hybrid"}}],
            "sentence_expanded",
        )
