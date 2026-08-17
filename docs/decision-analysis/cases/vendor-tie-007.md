# Case 7: Vendor Tie — Synthetic Tie Test Case

**Status:** Synthetic validation case. Values intentionally create a tie.

## Decision question

Do two eligible vendors remain tied when they receive identical scores on every weighted criterion?

## Options and criteria

| Option ID | Label |
|---|---|
| `vendor_a` | Vendor A |
| `vendor_b` | Vendor B |

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `annual_cost` | cost | USD/year | 0.5 |
| `support_quality` | benefit | 1–5 | 0.5 |

## Score matrix

| Option | Annual cost | Support quality |
|---|---:|---:|
| Vendor A | 100000 | 4 |
| Vendor B | 100000 | 4 |

All values are synthetic `user_provided` inputs.

## Expected result

Both options receive total score `1.0`. `vendor_a` displays first because input order is stable, but `tie_groups` must contain both option IDs. The API must not claim a material winner.

## API request

```json
{
  "title": "Verify vendor tie handling",
  "options": [
    {"id": "vendor_a", "label": "Vendor A"},
    {"id": "vendor_b", "label": "Vendor B"}
  ],
  "criteria": [
    {"id": "annual_cost", "label": "Annual cost", "direction": "cost", "weight": "0.5", "scale": "numeric"},
    {"id": "support_quality", "label": "Support quality", "direction": "benefit", "weight": "0.5", "scale": "ordinal"}
  ],
  "scores": [
    {"option_id": "vendor_a", "criterion_id": "annual_cost", "value": "100000", "provenance": "user_provided"},
    {"option_id": "vendor_a", "criterion_id": "support_quality", "value": "4", "provenance": "user_provided"},
    {"option_id": "vendor_b", "criterion_id": "annual_cost", "value": "100000", "provenance": "user_provided"},
    {"option_id": "vendor_b", "criterion_id": "support_quality", "value": "4", "provenance": "user_provided"}
  ]
}
```

## Required before real use

- Add a discriminating criterion or treat options as equivalent.
- Do not use request order to choose a vendor; it is only deterministic display order.
