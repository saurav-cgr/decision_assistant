# Decision Analysis Synthetic Test Suite

## Purpose

This suite contains ten repeatable test cases. They validate API contracts, weighted scoring, ties, sensitivity, provenance, and input rejection. They are synthetic and must not be reported as real business-decision accuracy.

## Cases

| ID | Case | Expected outcome | What it validates |
|---|---|---|---|
| 001 | [Hosting model](cases/hosting-model-001.md) | `managed`; sensitive | Cost vs quality trade-off |
| 002 | [Authentication approach](cases/authentication-approach-002.md) | `keycloak` | Three-option ranking |
| 003 | [Database platform](cases/database-platform-003.md) | `postgresql` | Multi-criterion ranking |
| 004 | [LLM deployment](cases/llm-deployment-004.md) | `provider_b` | Quality/privacy/cost trade-off |
| 005 | [Launch strategy](cases/launch-strategy-005.md) | `phased_beta` | Near-tie trade-off |
| 006 | [Observability platform](cases/observability-platform-006.md) | `managed_suite` | Cost/coverage trade-off |
| 007 | [Vendor tie](cases/vendor-tie-007.md) | tie | Tie groups and stable display order |
| 008 | [Incomplete matrix](cases/incomplete-matrix-008.md) | HTTP 422 | Missing-cell rejection |
| 009 | [Evidence provenance](cases/evidence-provenance-009.md) | `supplier_a`; evidence weight 1 | Citation-presence/provenance contract |
| 010 | [Staffing strategy](cases/staffing-strategy-010.md) | `hire`; 12 derived scores | Derived-input provenance |

## Final run checklist

1. Start services:

   ```bash
   docker compose up -d db api --wait
   ```

2. Run deterministic regression tests:

   ```bash
   docker compose run --rm api pytest \
     tests/unit/test_decision_analysis_scoring.py \
     tests/unit/test_decision_analysis_narrative.py \
     tests/integration/test_decision_analysis_api.py \
     tests/unit/test_decision_analysis_evaluation_fixture.py \
     tests/unit/test_evaluation_metrics.py -q
   ```

3. Submit every valid case JSON to:

   ```text
   POST http://localhost:8000/api/v1/decision-analyses
   ```

4. Confirm each documented winner, tie state, provenance count, and sensitivity result.

5. Confirm Case 008 returns `HTTP 422` and no ranking payload.

6. For one valid case, set `narrative_requested=true`; check that narrative recommendation equals deterministic rank 1.

7. Record result in [test report template](test-report-template.md).

8. Do not call synthetic results business validation. Collect and approve real cases before enabling a production workflow.

## Exit criteria

- Focused automated suite passes.
- All ten requests match documented expected outcome.
- Case 008 rejects invalid matrix.
- No response hides ties, rank reversals, or provenance warnings.
- At least ten real, expert-approved cases are planned before product release.
