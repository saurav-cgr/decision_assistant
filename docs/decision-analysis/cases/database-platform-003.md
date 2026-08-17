# Case 3: Database Platform — Synthetic Test Case

**Status:** Synthetic validation case. Values are test inputs, not technology-selection advice.

## Decision question

Which database platform best serves a transactional decision-assistant application with relational integrity, query flexibility, operating effort, and cost requirements?

## Options and criteria

| Option ID | Label |
|---|---|
| `postgresql` | PostgreSQL |
| `mongodb` | MongoDB |
| `dynamodb` | Amazon DynamoDB |

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `relational_integrity` | benefit | 1–5 | 0.4 |
| `operational_effort` | cost | 1–5 | 0.2 |
| `monthly_cost` | cost | USD/month | 0.15 |
| `query_flexibility` | benefit | 1–5 | 0.25 |

## Score matrix

| Option | Relational integrity | Operational effort | Monthly cost | Query flexibility |
|---|---:|---:|---:|---:|
| PostgreSQL | 5 | 3 | 400 | 5 |
| MongoDB | 3 | 3 | 450 | 3 |
| DynamoDB | 4 | 2 | 300 | 3 |

All values are synthetic `user_provided` scores.

## Expected result

Expected winner: `postgresql`.

Reason: relational integrity and query flexibility outweigh DynamoDB's operating-effort and cost advantage under these weights.

## API request

```json
{
  "title": "Choose database platform",
  "options": [
    {"id": "postgresql", "label": "PostgreSQL"},
    {"id": "mongodb", "label": "MongoDB"},
    {"id": "dynamodb", "label": "Amazon DynamoDB"}
  ],
  "criteria": [
    {"id": "relational_integrity", "label": "Relational integrity", "direction": "benefit", "weight": "0.4", "scale": "ordinal"},
    {"id": "operational_effort", "label": "Operational effort", "direction": "cost", "weight": "0.2", "scale": "ordinal"},
    {"id": "monthly_cost", "label": "Monthly cost", "direction": "cost", "weight": "0.15", "scale": "numeric"},
    {"id": "query_flexibility", "label": "Query flexibility", "direction": "benefit", "weight": "0.25", "scale": "ordinal"}
  ],
  "scores": [
    {"option_id": "postgresql", "criterion_id": "relational_integrity", "value": "5", "provenance": "user_provided"},
    {"option_id": "postgresql", "criterion_id": "operational_effort", "value": "3", "provenance": "user_provided"},
    {"option_id": "postgresql", "criterion_id": "monthly_cost", "value": "400", "provenance": "user_provided"},
    {"option_id": "postgresql", "criterion_id": "query_flexibility", "value": "5", "provenance": "user_provided"},
    {"option_id": "mongodb", "criterion_id": "relational_integrity", "value": "3", "provenance": "user_provided"},
    {"option_id": "mongodb", "criterion_id": "operational_effort", "value": "3", "provenance": "user_provided"},
    {"option_id": "mongodb", "criterion_id": "monthly_cost", "value": "450", "provenance": "user_provided"},
    {"option_id": "mongodb", "criterion_id": "query_flexibility", "value": "3", "provenance": "user_provided"},
    {"option_id": "dynamodb", "criterion_id": "relational_integrity", "value": "4", "provenance": "user_provided"},
    {"option_id": "dynamodb", "criterion_id": "operational_effort", "value": "2", "provenance": "user_provided"},
    {"option_id": "dynamodb", "criterion_id": "monthly_cost", "value": "300", "provenance": "user_provided"},
    {"option_id": "dynamodb", "criterion_id": "query_flexibility", "value": "3", "provenance": "user_provided"}
  ]
}
```

## Required before real use

- Replace scores with workload measurements and financial estimates.
- Define exact transaction, consistency, disaster-recovery, and scaling requirements.
- Add vendor-lock-in, team skill, and managed-service criteria if material.
- Obtain Architecture and SRE approval.
