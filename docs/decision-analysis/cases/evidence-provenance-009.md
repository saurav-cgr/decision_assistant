# Case 9: Evidence-Backed Inputs — Synthetic Provenance Test

**Status:** Synthetic validation case. UUIDs and quotes test provenance shape only; they are not active corpus passages.

## Purpose

Confirm that score inputs marked `evidence_backed` require citations and produce `evidence_backed_weight = 1` when every weighted criterion is fully evidence-backed.

## Decision question

Which supplier should be selected when implementation evidence is more important than operating cost?

## Options and criteria

| Option ID | Label |
|---|---|
| `supplier_a` | Supplier A |
| `supplier_b` | Supplier B |

| Criterion ID | Direction | Scale | Weight |
|---|---|---|---:|
| `implementation_evidence` | benefit | 1–5 | 0.7 |
| `operating_cost` | cost | USD/month | 0.3 |

## Expected result

Expected winner: `supplier_a`; expected evidence-backed weight: `1`.

## API request

```json
{
  "title": "Verify evidence-backed score provenance",
  "options": [
    {"id": "supplier_a", "label": "Supplier A"},
    {"id": "supplier_b", "label": "Supplier B"}
  ],
  "criteria": [
    {"id": "implementation_evidence", "label": "Implementation evidence", "direction": "benefit", "weight": "0.7", "scale": "ordinal"},
    {"id": "operating_cost", "label": "Operating cost", "direction": "cost", "weight": "0.3", "scale": "numeric"}
  ],
  "scores": [
    {"option_id": "supplier_a", "criterion_id": "implementation_evidence", "value": "5", "provenance": "evidence_backed", "citations": [{"passage_id": "00000000-0000-0000-0000-000000000011", "quote": "Supplier A completed all required integrations."}]},
    {"option_id": "supplier_a", "criterion_id": "operating_cost", "value": "100", "provenance": "evidence_backed", "citations": [{"passage_id": "00000000-0000-0000-0000-000000000012", "quote": "Supplier A monthly cost is 100."}]},
    {"option_id": "supplier_b", "criterion_id": "implementation_evidence", "value": "3", "provenance": "evidence_backed", "citations": [{"passage_id": "00000000-0000-0000-0000-000000000013", "quote": "Supplier B completed some required integrations."}]},
    {"option_id": "supplier_b", "criterion_id": "operating_cost", "value": "80", "provenance": "evidence_backed", "citations": [{"passage_id": "00000000-0000-0000-0000-000000000014", "quote": "Supplier B monthly cost is 80."}]}
  ]
}
```

## Pass criteria

- API accepts cited evidence-backed inputs.
- `supplier_a` ranks first.
- `evidence_coverage.evidence_backed_weight` equals `1`.
- Omitting any citation from an evidence-backed score returns `422`.

## Limitation

Current stateless endpoint checks citation presence, not whether UUID/quote exists in active corpus. Retrieval-backed passage verification is future work.
