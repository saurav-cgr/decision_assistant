# Case 5: Launch Strategy — Synthetic Near-Tie Test Case

**Status:** Synthetic validation case. Values are test inputs, not release advice.

## Decision question

Which launch strategy best balances time to market, reliability, security readiness, and delivery effort?

## Options and criteria

| Option ID | Label |
|---|---|
| `fast_launch` | Launch immediately |
| `phased_beta` | Phased internal beta |
| `delay_hardening` | Delay for hardening |

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `time_to_market` | benefit | 1–5 | 0.4 |
| `reliability` | benefit | 1–5 | 0.3 |
| `security_readiness` | benefit | 1–5 | 0.2 |
| `delivery_effort` | cost | 1–5 | 0.1 |

## Score matrix

| Option | Time to market | Reliability | Security readiness | Delivery effort |
|---|---:|---:|---:|---:|
| Launch immediately | 5 | 2 | 2 | 2 |
| Phased internal beta | 3 | 4 | 4 | 3 |
| Delay for hardening | 1 | 5 | 5 | 5 |

All values are synthetic `user_provided` inputs.

## Expected result

Expected winner: `phased_beta`.

This deliberately near-tied case checks that a balanced option can outrank faster and safer extremes. It should be tested with sensitivity enabled during manual review.

## API request

```json
{
  "title": "Choose launch strategy",
  "options": [
    {"id": "fast_launch", "label": "Launch immediately"},
    {"id": "phased_beta", "label": "Phased internal beta"},
    {"id": "delay_hardening", "label": "Delay for hardening"}
  ],
  "criteria": [
    {"id": "time_to_market", "label": "Time to market", "direction": "benefit", "weight": "0.4", "scale": "ordinal"},
    {"id": "reliability", "label": "Reliability", "direction": "benefit", "weight": "0.3", "scale": "ordinal"},
    {"id": "security_readiness", "label": "Security readiness", "direction": "benefit", "weight": "0.2", "scale": "ordinal"},
    {"id": "delivery_effort", "label": "Delivery effort", "direction": "cost", "weight": "0.1", "scale": "ordinal"}
  ],
  "scores": [
    {"option_id": "fast_launch", "criterion_id": "time_to_market", "value": "5", "provenance": "user_provided"},
    {"option_id": "fast_launch", "criterion_id": "reliability", "value": "2", "provenance": "user_provided"},
    {"option_id": "fast_launch", "criterion_id": "security_readiness", "value": "2", "provenance": "user_provided"},
    {"option_id": "fast_launch", "criterion_id": "delivery_effort", "value": "2", "provenance": "user_provided"},
    {"option_id": "phased_beta", "criterion_id": "time_to_market", "value": "3", "provenance": "user_provided"},
    {"option_id": "phased_beta", "criterion_id": "reliability", "value": "4", "provenance": "user_provided"},
    {"option_id": "phased_beta", "criterion_id": "security_readiness", "value": "4", "provenance": "user_provided"},
    {"option_id": "phased_beta", "criterion_id": "delivery_effort", "value": "3", "provenance": "user_provided"},
    {"option_id": "delay_hardening", "criterion_id": "time_to_market", "value": "1", "provenance": "user_provided"},
    {"option_id": "delay_hardening", "criterion_id": "reliability", "value": "5", "provenance": "user_provided"},
    {"option_id": "delay_hardening", "criterion_id": "security_readiness", "value": "5", "provenance": "user_provided"},
    {"option_id": "delay_hardening", "criterion_id": "delivery_effort", "value": "5", "provenance": "user_provided"}
  ],
  "sensitivity": {"range_percent": "0.2", "sample_count": 5}
}
```

## Required before real use

- Replace ordinal inputs with launch-readiness rubric evidence.
- Treat hard security/compliance requirements as eligibility gates, not weighted preferences.
- Obtain Product, Engineering, and Security approval.
