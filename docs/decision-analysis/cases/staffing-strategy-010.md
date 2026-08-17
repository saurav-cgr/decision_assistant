# Case 10: Staffing Strategy — Synthetic Derived-Input Test Case

**Status:** Synthetic validation case. Values represent derived planning estimates, not hiring advice.

## Decision question

Which staffing strategy best balances near-term delivery capacity, long-term knowledge, first-year cost, and management effort?

## Options and criteria

| Option ID | Label |
|---|---|
| `hire` | Hire full-time employee |
| `contractor` | Engage specialist contractor |
| `defer` | Defer initiative |

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `delivery_capacity` | benefit | 1–5 | 0.35 |
| `long_term_knowledge` | benefit | 1–5 | 0.25 |
| `first_year_cost` | cost | 1–5 | 0.25 |
| `management_effort` | cost | 1–5 | 0.15 |

## Score matrix

| Option | Delivery capacity | Long-term knowledge | First-year cost | Management effort |
|---|---:|---:|---:|---:|
| Hire full-time employee | 3 | 5 | 4 | 3 |
| Engage specialist contractor | 5 | 2 | 5 | 4 |
| Defer initiative | 1 | 1 | 1 | 1 |

All values are synthetic `derived` inputs. In real use, each must link to headcount plan, rate-card, and delivery-capacity calculation.

## Expected result

Expected winner: `hire`.

Reason: long-term knowledge and a balanced operational profile outweigh contractor delivery speed and deferral's short-term cost advantage.

## API request

```json
{
  "title": "Choose staffing strategy",
  "options": [
    {"id": "hire", "label": "Hire full-time employee"},
    {"id": "contractor", "label": "Engage specialist contractor"},
    {"id": "defer", "label": "Defer initiative"}
  ],
  "criteria": [
    {"id": "delivery_capacity", "label": "Delivery capacity", "direction": "benefit", "weight": "0.35", "scale": "ordinal"},
    {"id": "long_term_knowledge", "label": "Long-term knowledge", "direction": "benefit", "weight": "0.25", "scale": "ordinal"},
    {"id": "first_year_cost", "label": "First-year cost", "direction": "cost", "weight": "0.25", "scale": "ordinal"},
    {"id": "management_effort", "label": "Management effort", "direction": "cost", "weight": "0.15", "scale": "ordinal"}
  ],
  "scores": [
    {"option_id": "hire", "criterion_id": "delivery_capacity", "value": "3", "provenance": "derived", "rationale": "Derived staffing-plan estimate."},
    {"option_id": "hire", "criterion_id": "long_term_knowledge", "value": "5", "provenance": "derived", "rationale": "Derived retention estimate."},
    {"option_id": "hire", "criterion_id": "first_year_cost", "value": "4", "provenance": "derived", "rationale": "Derived total-compensation band."},
    {"option_id": "hire", "criterion_id": "management_effort", "value": "3", "provenance": "derived", "rationale": "Derived manager-capacity estimate."},
    {"option_id": "contractor", "criterion_id": "delivery_capacity", "value": "5", "provenance": "derived", "rationale": "Derived ramp-up estimate."},
    {"option_id": "contractor", "criterion_id": "long_term_knowledge", "value": "2", "provenance": "derived", "rationale": "Derived transfer-risk estimate."},
    {"option_id": "contractor", "criterion_id": "first_year_cost", "value": "5", "provenance": "derived", "rationale": "Derived rate-card estimate."},
    {"option_id": "contractor", "criterion_id": "management_effort", "value": "4", "provenance": "derived", "rationale": "Derived coordination estimate."},
    {"option_id": "defer", "criterion_id": "delivery_capacity", "value": "1", "provenance": "derived", "rationale": "Derived no-delivery outcome."},
    {"option_id": "defer", "criterion_id": "long_term_knowledge", "value": "1", "provenance": "derived", "rationale": "Derived no-learning outcome."},
    {"option_id": "defer", "criterion_id": "first_year_cost", "value": "1", "provenance": "derived", "rationale": "Derived no-spend outcome."},
    {"option_id": "defer", "criterion_id": "management_effort", "value": "1", "provenance": "derived", "rationale": "Derived no-management outcome."}
  ]
}
```

## Pass criteria

- `hire` ranks first.
- `derived_score_count` equals `12`.
- Warning states that derived scores affect ranking.
