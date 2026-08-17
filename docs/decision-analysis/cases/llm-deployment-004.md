# Case 4: LLM Deployment Model — Synthetic Test Case

**Status:** Synthetic validation case. Values are test inputs, not model-performance or pricing claims.

## Decision question

Which LLM deployment model best balances output quality, privacy fit, cost, and delivery effort for an internal decision assistant?

## Options and criteria

| Option ID | Label |
|---|---|
| `provider_a` | Managed provider A API |
| `provider_b` | Managed provider B API |
| `self_hosted` | Self-hosted open model |

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `output_quality` | benefit | 1–5 | 0.4 |
| `privacy_fit` | benefit | 1–5 | 0.25 |
| `operating_cost` | cost | 1–5 | 0.15 |
| `delivery_effort` | cost | 1–5 | 0.2 |

## Score matrix

| Option | Output quality | Privacy fit | Operating cost | Delivery effort |
|---|---:|---:|---:|---:|
| Managed provider A API | 4 | 2 | 4 | 2 |
| Managed provider B API | 5 | 2 | 5 | 2 |
| Self-hosted open model | 3 | 5 | 3 | 5 |

All values are synthetic `user_provided` inputs.

## Expected result

Expected winner: `provider_b`.

Reason: highest quality dominates under current weights; self-hosting privacy and cost advantages do not offset delivery effort and lower quality.

## API request

```json
{
  "title": "Choose LLM deployment model",
  "options": [
    {"id": "provider_a", "label": "Managed provider A API"},
    {"id": "provider_b", "label": "Managed provider B API"},
    {"id": "self_hosted", "label": "Self-hosted open model"}
  ],
  "criteria": [
    {"id": "output_quality", "label": "Output quality", "direction": "benefit", "weight": "0.4", "scale": "ordinal"},
    {"id": "privacy_fit", "label": "Privacy fit", "direction": "benefit", "weight": "0.25", "scale": "ordinal"},
    {"id": "operating_cost", "label": "Operating cost", "direction": "cost", "weight": "0.15", "scale": "ordinal"},
    {"id": "delivery_effort", "label": "Delivery effort", "direction": "cost", "weight": "0.2", "scale": "ordinal"}
  ],
  "scores": [
    {"option_id": "provider_a", "criterion_id": "output_quality", "value": "4", "provenance": "user_provided"},
    {"option_id": "provider_a", "criterion_id": "privacy_fit", "value": "2", "provenance": "user_provided"},
    {"option_id": "provider_a", "criterion_id": "operating_cost", "value": "4", "provenance": "user_provided"},
    {"option_id": "provider_a", "criterion_id": "delivery_effort", "value": "2", "provenance": "user_provided"},
    {"option_id": "provider_b", "criterion_id": "output_quality", "value": "5", "provenance": "user_provided"},
    {"option_id": "provider_b", "criterion_id": "privacy_fit", "value": "2", "provenance": "user_provided"},
    {"option_id": "provider_b", "criterion_id": "operating_cost", "value": "5", "provenance": "user_provided"},
    {"option_id": "provider_b", "criterion_id": "delivery_effort", "value": "2", "provenance": "user_provided"},
    {"option_id": "self_hosted", "criterion_id": "output_quality", "value": "3", "provenance": "user_provided"},
    {"option_id": "self_hosted", "criterion_id": "privacy_fit", "value": "5", "provenance": "user_provided"},
    {"option_id": "self_hosted", "criterion_id": "operating_cost", "value": "3", "provenance": "user_provided"},
    {"option_id": "self_hosted", "criterion_id": "delivery_effort", "value": "5", "provenance": "user_provided"}
  ]
}
```

## Required before real use

- Replace quality scores with versioned task benchmark results.
- Replace cost scores with workload-specific forecasts.
- Define privacy/data-residency requirements with Security and Legal.
- Include vendor reliability, quota, and exit-cost criteria when material.
