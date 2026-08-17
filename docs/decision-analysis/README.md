# Decision Analysis Testing Pack

Use this pack to test the deterministic decision-analysis API before adding persistence, retrieval-assisted scoring, or a user interface.

## Documents

- [Testing guide](testing-guide.md): end-to-end test procedure and release gates.
- [Case intake template](case-intake-template.md): collect real, expert-reviewed decisions.
- [Scoring rubric template](scoring-rubric-template.md): make ordinal scores consistent.
- [Test report template](test-report-template.md): record results and discrepancies.
- [Synthetic suite](synthetic-suite.md): ten repeatable API test cases and final checklist.

## Test sequence

1. Complete the scoring rubric for a decision domain.
2. Complete one case intake form per historical or planned decision.
3. Have a domain expert approve criteria, weights, scores, and expected outcome.
4. Submit the API request.
5. Record the result in the test report.
6. Add approved cases to `evaluation/decision_analysis_cases.json`.

The existing JSON fixture contains synthetic algorithm regression cases. It is not a substitute for real business ground truth.
