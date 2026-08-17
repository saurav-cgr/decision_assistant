# Case 2: Authentication Approach — Synthetic Test Case

**Status:** Synthetic validation case. Scores and expected outcome are test data, not a production recommendation.

## Decision question

Which authentication approach best balances delivery effort, security fit, customization, and cost for a new internal application?

## Options

| Option ID | Label |
|---|---|
| `auth0` | Managed identity provider |
| `keycloak` | Self-hosted Keycloak |
| `custom` | Custom authentication service |

## Criteria

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `monthly_cost` | cost | USD/month | 0.2 |
| `delivery_effort` | cost | 1–5, lower is faster | 0.3 |
| `security_fit` | benefit | 1–5, higher is better | 0.3 |
| `customization` | benefit | 1–5, higher is better | 0.2 |

All scores are `user_provided` synthetic inputs.

## Score matrix

| Option | Monthly cost | Delivery effort | Security fit | Customization |
|---|---:|---:|---:|---:|
| Managed identity provider | 1200 | 2 | 4 | 2 |
| Self-hosted Keycloak | 400 | 3 | 4 | 4 |
| Custom authentication service | 300 | 5 | 2 | 5 |

## Expected result

Expected winner: `keycloak`.

Expected order:

1. `keycloak`
2. `auth0`
3. `custom`

Reason: Keycloak retains high security fit, improves customization, and avoids managed-provider cost while carrying only moderate delivery effort.

## API request

```json
{
  "title": "Choose authentication approach",
  "options": [
    {"id": "auth0", "label": "Managed identity provider"},
    {"id": "keycloak", "label": "Self-hosted Keycloak"},
    {"id": "custom", "label": "Custom authentication service"}
  ],
  "criteria": [
    {"id": "monthly_cost", "label": "Monthly cost", "direction": "cost", "weight": "0.2", "scale": "numeric"},
    {"id": "delivery_effort", "label": "Delivery effort", "direction": "cost", "weight": "0.3", "scale": "ordinal"},
    {"id": "security_fit", "label": "Security fit", "direction": "benefit", "weight": "0.3", "scale": "ordinal"},
    {"id": "customization", "label": "Customization", "direction": "benefit", "weight": "0.2", "scale": "ordinal"}
  ],
  "scores": [
    {"option_id": "auth0", "criterion_id": "monthly_cost", "value": "1200", "provenance": "user_provided"},
    {"option_id": "auth0", "criterion_id": "delivery_effort", "value": "2", "provenance": "user_provided"},
    {"option_id": "auth0", "criterion_id": "security_fit", "value": "4", "provenance": "user_provided"},
    {"option_id": "auth0", "criterion_id": "customization", "value": "2", "provenance": "user_provided"},
    {"option_id": "keycloak", "criterion_id": "monthly_cost", "value": "400", "provenance": "user_provided"},
    {"option_id": "keycloak", "criterion_id": "delivery_effort", "value": "3", "provenance": "user_provided"},
    {"option_id": "keycloak", "criterion_id": "security_fit", "value": "4", "provenance": "user_provided"},
    {"option_id": "keycloak", "criterion_id": "customization", "value": "4", "provenance": "user_provided"},
    {"option_id": "custom", "criterion_id": "monthly_cost", "value": "300", "provenance": "user_provided"},
    {"option_id": "custom", "criterion_id": "delivery_effort", "value": "5", "provenance": "user_provided"},
    {"option_id": "custom", "criterion_id": "security_fit", "value": "2", "provenance": "user_provided"},
    {"option_id": "custom", "criterion_id": "customization", "value": "5", "provenance": "user_provided"}
  ]
}
```

## Required before real use

- Replace synthetic cost values with vendor quotes and internal operating estimates.
- Define ordinal score rubrics with Security and Engineering.
- Add compliance, identity federation, support, and migration criteria if material.
- Obtain Security and Engineering approval before treating outcome as a recommendation.
