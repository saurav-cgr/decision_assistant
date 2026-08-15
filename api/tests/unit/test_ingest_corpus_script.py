import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path("/workspace/scripts/ingest_corpus.py")


def _load_script():
    spec = importlib.util.spec_from_file_location("ingest_corpus", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ingest_corpus"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


def test_checksum_is_sha256_of_file_bytes(script, tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("content", encoding="utf-8")
    assert script._checksum(path) == hashlib.sha256(b"content").hexdigest()


def test_ingest_uploads_supported_files_in_sorted_order(script, tmp_path: Path) -> None:
    source = tmp_path / "sources"
    source.mkdir()
    (source / "b.txt").write_text("b", encoding="utf-8")
    (source / "a.md").write_text("a", encoding="utf-8")
    (source / "skip.log").write_text("skip", encoding="utf-8")

    uploaded: list[str] = []

    def fake_upload(workspace_id: str, path: Path) -> dict:
        uploaded.append(path.name)
        return {"results": [{"status": "accepted", "document_id": f"doc-{path.name}"}]}

    def fake_wait(workspace_id: str, document_id: str, timeout: float) -> dict:
        filename = document_id.replace("doc-", "")
        return {
            "active_version": {"id": "v1", "state": "active", "chunking_profile": {"algorithm": "structural-token-v1"}},
            "passages": [{"id": "p1"}],
        }

    script._request_json = lambda *a, **k: {}  # workspace listing/activate
    script._find_or_create_workspace = lambda name: "ws-1"
    script._upload = fake_upload
    script._wait_for_active = fake_wait

    summary = script.ingest(
        source_directory=source,
        workspace_name="Atlas",
        timeout=10,
        extensions={".md", ".txt"},
    )

    assert [item["filename"] for item in summary] == ["a.md", "b.txt"]
    assert [item["passage_count"] for item in summary] == [1, 1]
    assert all(item["chunking_profile"]["algorithm"] == "structural-token-v1" for item in summary)
    assert "skip.log" not in uploaded


def test_ingest_fails_nonzero_on_rejected_upload(script, tmp_path: Path) -> None:
    source = tmp_path / "sources"
    source.mkdir()
    (source / "a.md").write_text("a", encoding="utf-8")

    script._find_or_create_workspace = lambda name: "ws-1"
    script._upload = lambda *a, **k: {"results": [{"status": "rejected", "error": "bad"}]}

    with pytest.raises(script.IngestFailure):
        script.ingest(
            source_directory=source,
            workspace_name="Atlas",
            timeout=10,
            extensions={".md"},
        )


def test_ingest_fails_when_source_directory_missing(script, tmp_path: Path) -> None:
    with pytest.raises(script.IngestFailure):
        script.ingest(
            source_directory=tmp_path / "missing",
            workspace_name="Atlas",
            timeout=10,
            extensions={".md"},
        )
