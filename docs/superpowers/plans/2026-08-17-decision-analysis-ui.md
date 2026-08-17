# Decision Analysis UI Implementation Plan

**Design:** `docs/superpowers/specs/2026-08-17-decision-analysis-ui-design.md`
**Status:** Proposed

## Guardrails

- Keep weighted scoring server-authoritative.
- Preserve existing dirty-worktree files.
- Use no dependency or schema change.
- Start with `user_provided` and `derived` inputs only; evidence-backed UI waits for active-passage verification.
- Keep source files below 500 lines.

## Step 1 — Client contract

Add decision-analysis TypeScript types and typed API function. Add client tests proving request path, method, and Decimal-string payload handling.

## Step 2 — Form route

Add route/navigation and form editor. Cover local validation, row add/remove, matrix completeness, and API error behavior.

## Step 3 — Result display

Add ranking, contribution, tie, sensitivity, provenance, warnings, and narrative display. Cover accessibility and responsive behavior.

## Step 4 — Acceptance

Run web tests/build and manually execute synthetic Case 001 through the UI. Document any UI/API mismatch.
