# Decision Analysis Case Intake

Copy this template once for every real test case.

## Identity

```text
Case ID:
Decision title:
Decision question:
Time horizon:
Decision owner:
Domain expert reviewer:
Review date:
```

## Decision scope

```text
What outcome is being optimized?
What constraints are non-negotiable?
What would make this decision invalid or obsolete?
```

## Options

| Option ID | Label | Description | Eligible? | Notes |
|---|---|---|---|---|
|  |  |  | Yes / No |  |

## Criteria and weights

| Criterion ID | Label | Direction | Unit/scale | Weight | Score owner |
|---|---|---|---|---:|---|
|  |  | benefit / cost |  |  |  |

Weight total: `_____` — must equal `1.0`.

## Score matrix

| Option | Criterion | Value | Provenance | Rationale | Evidence quote/source | Reviewer |
|---|---|---:|---|---|---|---|
|  |  |  | user_provided / derived / evidence_backed |  |  |  |

Rules:

- Provide one row for every option × criterion pair.
- `evidence_backed` requires exact evidence quote and passage/source ID when available.
- `derived` requires formula or calculation reference.
- `user_provided` requires accountable reviewer.

## Expected result before API call

```text
Expected winner option ID:
Acceptable runner-up option IDs:
Expected stability: stable / sensitive
Expected rank-reversal condition:
Reason this outcome is acceptable:
```

## Approval

```text
Expert approval: approved / rejected
Name:
Date:
Comments:
```
