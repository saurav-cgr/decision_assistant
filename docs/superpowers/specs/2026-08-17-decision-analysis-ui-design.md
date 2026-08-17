# Decision Analysis UI Design

**Date:** 2026-08-17
**Status:** Proposed
**Objective:** Provide an accessible React workflow for creating a stateless weighted-sum decision analysis and inspecting its deterministic result.

## Scope

Add a `/decision-analysis` route to the existing web app. The page calls `POST /api/v1/decision-analyses`; it does not require a workspace, database persistence, document retrieval, or a provider call by default.

The page must support:

1. decision title;
2. options with stable request-local IDs and labels;
3. criteria with benefit/cost direction, numeric/ordinal scale, and Decimal-compatible weight;
4. complete option-by-criterion score matrix with provenance and rationale;
5. client-side completeness and weight-total guidance;
6. server validation and error display;
7. result display for rank, total, contributions, ties, sensitivity, provenance, and warnings; and
8. optional narrative request behind an explicit checkbox.

## Ownership

Backend remains source of truth for scoring, normalization, totals, tie groups, sensitivity, and verification. React owns only form state, local input guidance, request construction, and display.

The client may calculate a display-only weight total. It must not calculate or present an independent ranking.

## Information Architecture

Add `Decision Analysis` after `Ask` in primary navigation.

```text
Decision Analysis
  Decision details
  Options
  Criteria
  Score matrix
  Analyze button
  Result: ranking, trade-offs, sensitivity, provenance, narrative
```

Use one route-level `DecisionAnalysis` page with small presentational components when the file would otherwise exceed 500 lines.

## Request Contract

Add TypeScript request/response types mirroring backend Pydantic schemas. Values and weights remain strings in browser state, then are posted as strings so backend Decimal handling remains authoritative.

Initial form state:

- title: empty;
- options: two empty rows;
- criteria: two empty rows, default `benefit`, `ordinal`, weights `0.5` and `0.5`;
- matrix: blank `user_provided` score cells;
- sensitivity: enabled, range `0.2`, sample count `5`;
- narrative: disabled.

Generate stable client-local IDs when an option or criterion is added. Never derive an ID from mutable labels after score rows exist.

## Validation and Error Behavior

Disable Analyze until the form has a title, at least two options, at least one criterion, nonblank IDs/labels, a unique option/criterion matrix, numeric nonnegative score values, and weights totaling exactly `1.0` under Decimal-compatible string arithmetic.

Client guidance is not an authority boundary. Submit remains validated by the API. Display server-side `422` errors through the existing API error pattern.

Show all remaining assumptions via provenance labels. `evidence_backed` mode is not exposed in this first UI because its citations cannot yet be verified against active corpus passages; UI supports `user_provided` and `derived` only.

## Result Behavior

Display:

- recommendation card: rank 1 option, total, verification status;
- ordered ranking table with each criterion contribution;
- tie callout when `tie_groups` is nonempty;
- sensitivity callout with reversing criterion IDs and sample outcomes;
- provenance summary and verifier warnings;
- optional narrative only when `narrative_status="generated"`.

When sensitivity is `sensitive`, wording must say the result depends on the submitted weights; it must not say the winner is certain.

## Accessibility and Tests

- Use labels for every input and table header scopes for score matrix.
- Use `aria-live="polite"` for calculation progress/result state and `role="alert"` for errors.
- Preserve keyboard access for adding/removing rows and navigating matrix fields.
- Add Testing Library coverage for validation, request payload, server error, sensitive result, tie result, and optional narrative output.
- Add typed API-client tests for endpoint request construction.

## Delivery Steps

1. Add decision-analysis client types and API client function with unit tests.
2. Add route, navigation, form state, and validation with UI tests.
3. Add result components and success/error/sensitivity/tie/narrative tests.
4. Run web tests and production build; manually submit synthetic Case 001 through UI.

No schema migration, dependency, provider change, or persistence is part of this UI slice.
