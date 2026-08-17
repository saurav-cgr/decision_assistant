# Decision Analysis Testing Guide

## Purpose

Validate that the decision-analysis feature produces reproducible rankings, exposes its assumptions, and matches approved decision policy.

## Prerequisites

Start the API:

```bash
docker compose up -d db api --wait
```

Use this endpoint:

```text
POST http://localhost:8000/api/v1/decision-analyses
```

Run deterministic regression tests:

```bash
docker compose run --rm api pytest \
  tests/unit/test_decision_analysis_scoring.py \
  tests/unit/test_decision_analysis_narrative.py \
  tests/integration/test_decision_analysis_api.py \
  tests/unit/test_decision_analysis_evaluation_fixture.py -q
```

## Case selection

Collect 10–20 cases after expert review.

| Type | Target count | Purpose |
|---|---:|---|
| Normal two-option decision | 6–8 | Validate standard ranking |
| Three-plus option decision | 2–3 | Validate ranking order |
| Cost/quality trade-off | 2–3 | Validate benefit/cost direction |
| Risk/speed trade-off | 2–3 | Validate decision policy |
| Sensitive decision | 2 | Validate rank-reversal output |
| Tie or near-tie | 1 | Validate tie presentation |
| Incomplete input | 1 | Validate request rejection |
| Conflicting evidence | 1 | Reserve for retrieval-assisted phase |

Do not use fabricated cases to claim product quality. Synthetic fixtures prove arithmetic; real cases test decision usefulness.

## Per-case procedure

1. Complete [case intake](case-intake-template.md).
2. Define score meanings in [scoring rubric](scoring-rubric-template.md).
3. Get a domain expert to approve inputs before calling the API.
4. Submit request with `narrative_requested=false`.
5. Check that weights sum to `1.0` and all option/criterion cells are present.
6. Check raw values, normalized values, weighted contributions, rank, and tie groups.
7. Check sensitivity output; document every winner reversal.
8. If required, submit same request with `narrative_requested=true` and verify narrative does not contradict rank or source data.
9. Complete [test report](test-report-template.md).

## Expected behavior

- Benefit criterion: larger raw value receives a larger normalized value.
- Cost criterion: smaller raw value receives a larger normalized value.
- Equal raw values normalize to `1` for every option and do not distinguish options.
- Weight total must equal exactly `1.0`.
- Missing or duplicate option/criterion score cells return `422`.
- Results use Decimal values serialized as strings.
- A tie is returned in `tie_groups`; request option order breaks display ordering only.
- `sensitive` means at least one tested weight variation changed the top option.
- Narrative failure returns verified analysis with `narrative_status="unavailable"`.

## Release gates

| Gate | Required result |
|---|---|
| Formula correctness | 100% pass for hand-calculated fixtures |
| Real-case agreement | ≥80% expert-approved winner agreement |
| Unsupported decisive value | 0 accepted as evidence-backed |
| Provenance | Every score labeled user-provided, derived, or evidence-backed |
| Sensitivity | All rank reversals visible in result/report |
| API reliability | Focused regression suite passes |

## Failure triage

| Symptom | Likely cause | Action |
|---|---|---|
| Unexpected winner | Score, weight, direction, or omitted criterion | Review case intake with expert |
| Winner changes easily | Legitimate sensitivity or poor weight policy | Present scenarios; do not hide change |
| API returns 422 | Invalid matrix or weights | Correct request data |
| Narrative contradicts result | Invalid LLM output | Treat narrative unavailable; inspect diagnostics later |
| Evidence weak | Assumption mislabeled as source fact | Change provenance to user-provided/derived |
