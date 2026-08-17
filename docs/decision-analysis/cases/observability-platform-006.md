# Case 6: Observability Platform — Synthetic Test Case

**Status:** Synthetic validation case. Values are test inputs, not vendor guidance.

## Decision question

Which observability platform best balances coverage, delivery effort, cost, and integration quality?

## Options and criteria

| Option ID | Label |
|---|---|
| `managed_suite` | Managed observability suite |
| `open_stack` | Open-source observability stack |
| `custom_stack` | Custom-built observability stack |

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `coverage` | benefit | 1–5 | 0.35 |
| `delivery_effort` | cost | 1–5 | 0.2 |
| `operating_cost` | cost | 1–5 | 0.25 |
| `integration_quality` | benefit | 1–5 | 0.2 |

## Score matrix

| Option | Coverage | Delivery effort | Operating cost | Integration quality |
|---|---:|---:|---:|---:|
| Managed suite | 5 | 2 | 5 | 5 |
| Open-source stack | 4 | 3 | 2 | 4 |
| Custom stack | 2 | 5 | 1 | 2 |

All values are synthetic `user_provided` inputs.

## Expected result

Expected winner: `managed_suite`.

Reason: immediate coverage, low delivery effort, and integration quality outweigh its operating-cost disadvantage under current weights.

## API request

```json
{
  "title": "Choose observability platform",
  "options": [
    {"id": "managed_suite", "label": "Managed observability suite"},
    {"id": "open_stack", "label": "Open-source observability stack"},
    {"id": "custom_stack", "label": "Custom-built observability stack"}
  ],
  "criteria": [
    {"id": "coverage", "label": "Coverage", "direction": "benefit", "weight": "0.35", "scale": "ordinal"},
    {"id": "delivery_effort", "label": "Delivery effort", "direction": "cost", "weight": "0.2", "scale": "ordinal"},
    {"id": "operating_cost", "label": "Operating cost", "direction": "cost", "weight": "0.25", "scale": "ordinal"},
    {"id": "integration_quality", "label": "Integration quality", "direction": "benefit", "weight": "0.2", "scale": "ordinal"}
  ],
  "scores": [
    {"option_id": "managed_suite", "criterion_id": "coverage", "value": "5", "provenance": "user_provided"},
    {"option_id": "managed_suite", "criterion_id": "delivery_effort", "value": "2", "provenance": "user_provided"},
    {"option_id": "managed_suite", "criterion_id": "operating_cost", "value": "5", "provenance": "user_provided"},
    {"option_id": "managed_suite", "criterion_id": "integration_quality", "value": "5", "provenance": "user_provided"},
    {"option_id": "open_stack", "criterion_id": "coverage", "value": "4", "provenance": "user_provided"},
    {"option_id": "open_stack", "criterion_id": "delivery_effort", "value": "3", "provenance": "user_provided"},
    {"option_id": "open_stack", "criterion_id": "operating_cost", "value": "2", "provenance": "user_provided"},
    {"option_id": "open_stack", "criterion_id": "integration_quality", "value": "4", "provenance": "user_provided"},
    {"option_id": "custom_stack", "criterion_id": "coverage", "value": "2", "provenance": "user_provided"},
    {"option_id": "custom_stack", "criterion_id": "delivery_effort", "value": "5", "provenance": "user_provided"},
    {"option_id": "custom_stack", "criterion_id": "operating_cost", "value": "1", "provenance": "user_provided"},
    {"option_id": "custom_stack", "criterion_id": "integration_quality", "value": "2", "provenance": "user_provided"}
  ]
}
```

## Required before real use

- Replace values with telemetry volume, retention, staffing, and incident-response data.
- Add compliance, data residency, lock-in, and migration criteria if material.
- Obtain SRE and Finance approval.
