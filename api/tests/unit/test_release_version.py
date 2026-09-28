"""T068/FR-025: the release version is single-sourced, semver-shaped, and has a changelog entry.

Why this is a test and not a convention: `/health` reports the *API* package's `project.version`
while the web app is a separate package with its own `version`, and the changelog is a third place a
version is written down. Without a check they drift, and the installed report ("what version am I
running?") stops answering the question. The `Corpus rebuild on upgrade:` line is required by FR-025
and is the one line an operator needs before upgrading, so it is asserted rather than trusted.

`web/package.json` and `CHANGELOG.md` live outside the `api` build context, so `compose.test.yml`
mounts both read-only — the same treatment `scripts/` and `evaluation/` already get.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
WEB_PACKAGE = Path("/workspace/web/package.json")
CHANGELOG = Path("/workspace/CHANGELOG.md")

#: `MAJOR.MINOR.PATCH`, optionally with a pre-release/build suffix (SemVer 2.0.0).
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

#: A released-version heading. The format documentation's example uses `[X.Y.Z]`, which deliberately
#: does not match.
RELEASE_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\]", re.MULTILINE)

REBUILD_LINE = re.compile(r"^Corpus rebuild on upgrade: (yes|no)\b", re.MULTILINE)


def _api_version() -> str:
    text = (API_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None, "api/pyproject.toml declares no project version"
    return match.group(1)


def _web_version() -> str:
    return json.loads(WEB_PACKAGE.read_text(encoding="utf-8"))["version"]


def _changelog() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def test_api_version_is_semver() -> None:
    assert SEMVER.match(_api_version()), f"{_api_version()!r} is not a SemVer version"


def test_web_version_matches_the_api_version() -> None:
    version = _api_version()
    # The web app is what displays the version, so a mismatch means the UI reports a version the API
    # is not running.
    assert _web_version() == version, (
        f"web/package.json says {_web_version()!r} but api/pyproject.toml says {version!r}"
    )


def test_changelog_has_an_entry_for_the_current_version() -> None:
    version = _api_version()
    assert f"## [{version}]" in _changelog(), (
        f"CHANGELOG.md has no entry for the released version {version}"
    )


def test_every_changelog_entry_states_its_corpus_rebuild_impact() -> None:
    """FR-025: each release says whether upgrading re-ingests the corpus, and why."""
    text = _changelog()
    headings = list(RELEASE_HEADING.finditer(text))
    assert headings, "CHANGELOG.md contains no released-version entry"

    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.start() : end]
        match = REBUILD_LINE.search(section)
        assert match is not None, (
            f"CHANGELOG.md entry {heading.group(1)} has no "
            "'Corpus rebuild on upgrade: yes|no' line (FR-025)"
        )
        # `yes`/`no` alone is not an answer an operator can plan around: the line continues with the
        # reason (an em dash introduces it).
        assert "—" in section[match.end() : match.end() + 200], (
            f"CHANGELOG.md entry {heading.group(1)}: the corpus-rebuild line states the impact but "
            "not why"
        )
