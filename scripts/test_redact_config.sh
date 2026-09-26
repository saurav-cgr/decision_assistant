#!/bin/sh
# Regression fixture for scripts/redact_config.awk. Feeds a synthetic YAML
# fixture (fake secrets only) through the script and diffs it against the
# checked-in expected output. Locks in every case found by checker verdicts
# V38, V40, V41, V42 so a future edit to the awk script cannot silently
# regress one of them.
set -eu
cd "$(dirname "$0")/.."

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

awk -f scripts/redact_config.awk scripts/fixtures/redact_config/input.yaml > "$tmp"

if diff -u scripts/fixtures/redact_config/expected.txt "$tmp"; then
    echo "redact_config.awk fixture: OK"
else
    echo "redact_config.awk fixture: MISMATCH" >&2
    exit 1
fi
