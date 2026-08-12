"""Validate every gold reference resolves uniquely against the parsed corpus."""
import json
from pathlib import Path

from decision_assistant.ingestion.parsers import parse_document

ROOT = Path("/workspace")
ATLAS = ROOT / "sample_data" / "atlas"
QUESTIONS = json.loads((ROOT / "evaluation" / "questions.json").read_text())


def main() -> None:
    docs = {}
    for path in ATLAS.glob("*"):
        if path.suffix not in (".md", ".txt", ".pdf", ".docx"):
            continue
        try:
            parsed = parse_document(path)
        except Exception as exc:  # noqa: BLE001
            print("PARSE FAIL", path.name, type(exc).__name__, exc)
            continue
        docs[path.name] = parsed

    problems = []
    total = 0
    for q in QUESTIONS["questions"]:
        for ref in q.get("expected_passages", []):
            total += 1
            doc_name = ref.get("document")
            parsed = docs.get(doc_name)
            if parsed is None:
                problems.append((q["id"], doc_name, "no-doc", None))
                continue
            quote = ref.get("quote")
            locator = ref.get("locator")
            # Resolve against source blocks (the grounding contract), matching
            # tests/unit/test_evaluation_fixture.py. Chunk-level uniqueness is
            # not required here because overlapping chunks legitimately share
            # boundary lines, which would otherwise raise false positives.
            matches = [
                block
                for block in parsed.blocks
                if isinstance(quote, str)
                and quote in block.text
                and isinstance(locator, dict)
                and block.locator == locator
            ]
            if len(matches) != 1:
                actual = [f"{block.locator}" for block in matches[:4]]
                problems.append((q["id"], doc_name, f"count={len(matches)}", actual))

    print(f"total gold passage refs: {total}")
    print(f"problems: {len(problems)}")
    for qid, doc, why, actual in problems:
        print(f"  {qid} | {doc} | {why} | {actual}")


if __name__ == "__main__":
    main()
