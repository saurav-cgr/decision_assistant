# Case 1: Hosting Model — Provisional Test Case

**Status:** Provisional synthetic validation case. Values came from the initial API request and are not approved business facts.

## Identity

| Field | Value |
|---|---|
| Case ID | `hosting-model-001` |
| Decision | Choose hosting model |
| Time horizon | Not yet defined |
| Decision owner | Unassigned |
| Expert reviewer | Unassigned |

## Decision question

Which hosting model should be selected when quality receives 60% of the decision weight and monthly cost receives 40%?

## Options

| Option ID | Label |
|---|---|
| `managed` | Managed cloud |
| `self_hosted` | Self-hosted |

## Criteria and score definitions

| Criterion ID | Direction | Scale | Weight | Definition |
|---|---|---|---:|---|
| `monthly_cost` | cost | currency/month | 0.4 | Lower expected monthly cost is better. |
| `quality` | benefit | ordinal 1–10 | 0.6 | Higher product/model quality is better. Rubric still required. |

## Score matrix

| Option | Criterion | Value | Provenance | Rationale/evidence |
|---|---|---:|---|---|
| Managed cloud | Monthly cost | 100 | user_provided | Initial test input. |
| Managed cloud | Quality | 8 | user_provided | Initial test input. |
| Self-hosted | Monthly cost | 40 | user_provided | Initial test input. |
| Self-hosted | Quality | 6 | user_provided | Initial test input. |

## API result

| Rank | Option | Total score |
|---:|---|---:|
| 1 | Managed cloud | 0.6 |
| 2 | Self-hosted | 0.4 |

No tie occurred.

Sensitivity result: **sensitive**. Reducing `quality` weight from `0.60` to `0.48` made `self_hosted` the winner. Varying `monthly_cost` from `0.32` to `0.48` did not change the winner.

## Required expert completion

1. Define time horizon, included costs, and currency.
2. Define quality scoring rubric; replace uncalibrated 1–10 values.
3. Assign decision owner and expert reviewer.
4. Replace assumptions with vendor quotes, benchmark results, or transparent calculations.
5. Confirm whether `managed` is expected winner under approved weights.
6. Re-run API and move this case to approved benchmark only after sign-off.
