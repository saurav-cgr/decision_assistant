# Decision Analysis Scoring Rubric

Create one rubric per reusable criterion. Do not reuse ordinal values across domains unless their meanings match.

## Criterion definition

```text
Criterion ID:
Label:
Direction: benefit / cost
Scale: numeric / ordinal
Unit:
Score owner:
Evidence required for evidence_backed score:
```

## Numeric criterion

Use raw, comparable units.

Example:

| Criterion | Direction | Unit | Measurement period |
|---|---|---|---|
| Monthly cost | cost | USD per month | First 12 months |

Document inclusions/exclusions:

```text
Include: infrastructure, licensing, support.
Exclude: sunk cost, unrelated team salaries.
```

## Ordinal criterion

Define every allowed score before evaluating options.

Example: operational risk, direction `cost`.

| Score | Meaning | Evidence/example |
|---:|---|---|
| 1 | Minimal operational risk | Existing supported platform; normal monitoring |
| 2 | Low risk | Small new configuration; documented rollback |
| 3 | Moderate risk | New operational process; bounded failure mode |
| 4 | High risk | New dependency or major on-call burden |
| 5 | Critical risk | Unproven operation; no viable rollback |

## Calibration rules

```text
Minimum evidence required:
When score must be derived:
Who resolves reviewer disagreement:
When rubric must be revised:
```

Changing a rubric after results exist creates a new evaluation basis. Record changed version and rerun affected cases.
