# Option A: Evidence-Grounded Decision Analysis

**Date:** 2026-08-17
**Status:** Proposed
**Objective:** Add auditable multi-criteria decision analysis (MCDA) to the existing decision-memory assistant without introducing a multi-agent runtime, external orchestration framework, or a second source of domain truth in the web client.

## 1. Decision

Implement a backend-owned decision-analysis module that:

1. accepts options, criteria, weights, and explicitly supplied assumptions;
2. retrieves and extracts evidence using the existing hybrid-retrieval and provider interfaces;
3. calculates rankings deterministically using weighted-sum scoring in the first release;
4. performs deterministic one-way sensitivity analysis;
5. permits an LLM to explain verified results but never to determine the final numeric rank; and
6. returns score provenance, citations, missing inputs, conflicts, and instability warnings.

TOPSIS and AHP are deferred. The initial weighted-sum model is easier to audit, test, explain, and validate against hand-calculated fixtures. The domain model and algorithm-version fields must permit a later additive TOPSIS implementation without changing historic results.

## 2. Scope

### In scope

- A new `decision_analysis` backend module with Pydantic request/response models, pure scoring logic, validation, service, router, and focused tests.
- Numeric and ordinal criteria with an explicit direction: `benefit` (higher is better) or `cost` (lower is better).
- User-provided score inputs and evidence-backed score inputs with explicit provenance.
- A weight total of exactly 1.0, represented and calculated with `Decimal` rather than binary floating point.
- Min-max normalization across complete option values for each criterion.
- Weighted-sum ranking, deterministic tie handling, and deterministic one-way weight sensitivity.
- Evidence citations for evidence-backed scores, reusing active-version checks and exact-source locators.
- A one-call structured LLM narrative generated only after scoring and verification. The narrative is optional in the first endpoint and fails closed to the verified data result when generation fails.
- Evaluation fixtures for formula correctness, missing values, unsupported evidence, ties, and rank reversals.

### Out of scope

- LangGraph, AutoGen, agents, graph checkpoints, and tool-using autonomous workflows.
- Schema changes, persistence, historical decision runs, asynchronous jobs, or UI work in the first vertical slice.
- Web search and third-party data connectors.
- AHP pairwise preference elicitation, TOPSIS, Monte Carlo simulation, group voting, and portfolio optimization.
- Treating model self-reported confidence as a calibrated probability.

The first slice is intentionally stateless. It proves algorithm correctness and the evidence contract before a database schema or long-lived workflow is introduced.

## 3. Domain Contract

### 3.1 Request model

```python
DecisionAnalysisRequest(
    title: str,
    options: list[DecisionOption],
    criteria: list[DecisionCriterion],
    scores: list[ScoreInput],
    sensitivity: SensitivityRequest | None,
    narrative_requested: bool = False,
)

DecisionOption(id: str, label: str, description: str | None)

DecisionCriterion(
    id: str,
    label: str,
    direction: Literal["benefit", "cost"],
    weight: Decimal,
    scale: Literal["numeric", "ordinal"],
)

ScoreInput(
    option_id: str,
    criterion_id: str,
    value: Decimal,
    provenance: Literal[
        "user_provided",
        "evidence_backed",
        "derived",
    ],
    rationale: str | None,
    citations: list[ScoreCitation],
)
```

Rules:

- Require 2–20 options and 1–12 criteria.
- Option, criterion, and score identifiers are request-local opaque IDs, not database IDs.
- Each option/criterion pair appears exactly once. Missing pairs are a validation failure in v1; scores are never silently imputed.
- Criterion weights must be non-negative, with at least one positive value and sum exactly `1.0` after a documented Decimal quantization policy.
- Scores must be finite, non-negative Decimal values. Cross-criterion comparison is only made after per-criterion normalization.
- `evidence_backed` inputs require one or more supplied citations. `user_provided` and `derived` inputs must not claim source citations as proof.
- A criterion with identical values for every option produces normalized score `1.0` for every option; it does not create a false distinction.

### 3.2 Response model

```python
DecisionAnalysisResponse(
    algorithm_version: "weighted-sum-v1",
    ranked_options: list[RankedOption],
    criterion_breakdowns: list[CriterionBreakdown],
    sensitivity: SensitivityResult | None,
    evidence_coverage: EvidenceCoverage,
    verification: DecisionVerification,
    narrative: GeneratedDecisionNarrative | None,
)
```

The response must expose raw values, normalized values, weighted contributions, total scores, deterministic ranks, tie groups, score provenance, validation warnings, and rank-instability outcomes. A client must be able to reproduce every total from the response without calling a model.

## 4. Deterministic Scoring

For each criterion `c` and option `o`, calculate normalized score `n(o,c)`:

- benefit criterion: `(value - min) / (max - min)`;
- cost criterion: `(max - value) / (max - min)`;
- equal values: `1` for every option.

Calculate each contribution as `weight(c) * n(o,c)` and each option total as the sum of contributions. Sort by total descending, then use the original request option order as a stable deterministic tie-breaker. Return tie groups separately so the presentation layer does not mistake tie-break order for material superiority.

All calculations use `Decimal`; response values are serialized as strings. The algorithm module has no database, network, provider, or FastAPI dependencies.

## 5. Sensitivity Analysis

When requested, vary one criterion weight within a caller-supplied bounded percentage range while proportionally rebalancing remaining positive weights. Recalculate ranks for each deterministic sample point.

Return:

- the baseline winner;
- whether the winner changes;
- every sampled configuration where a winner change occurs;
- the criteria capable of reversing the winner; and
- a stability label: `stable`, `sensitive`, or `indeterminate`.

`indeterminate` is reserved for invalid or incomplete input and must not be generated for fully valid v1 requests.

## 6. Evidence and LLM Boundaries

The existing retrieval, evidence-pack, citation, and verification contracts remain authoritative.

- The v1 request carries score citations explicitly; it does not yet call retrieval automatically.
- A follow-up endpoint may accept an evidence query, invoke `HybridRetrievalService`, and use the generation provider to produce candidate score inputs. Such candidates remain untrusted until the decision-analysis verifier confirms the cited evidence belongs to the supplied active evidence pack.
- The LLM sees a verified result payload only when generating a narrative. It may explain trade-offs and assumptions, but cannot alter rankings, totals, weights, raw inputs, or stability labels.
- Narrative output is Pydantic-constrained and must reference only option IDs, criterion IDs, and citations supplied in the verified payload.
- Narrative failure never invalidates the deterministic result; return the verified result with `narrative=None` and a bounded diagnostic status.

## 7. Confidence and Verification

The system must not return LLM self-assessed confidence. It returns computed diagnostics:

- `input_completeness`: all option/criterion cells supplied;
- `evidence_backed_weight`: sum of weights whose values are evidence-backed for all options;
- `sensitivity_stability`: stable/sensitive;
- `provenance_summary`: counts by provenance class;
- `warnings`: user assumptions, derived values, missing citation problems, and equal-value criteria.

The decision verifier rejects malformed weights, duplicate or missing score cells, out-of-contract citations, non-finite values, invalid algorithm outputs, and narrative attempts to contradict computed totals.

## 8. HTTP Interface

Add a versioned endpoint:

```text
POST /api/v1/decision-analyses
```

The endpoint is stateless in v1 and returns `200` on a valid, fully calculated result. Use FastAPI/Pydantic validation errors for invalid decision models. No schema migration is required for this endpoint.

Future persistence must be an additive, separately approved schema change. A persisted run will need workspace ownership, immutable request/result snapshots, algorithm and provider profiles, evidence passage IDs, and a retention policy.

## 9. Testing and Acceptance

Required focused tests:

1. benefit and cost normalization with hand-calculated expected totals;
2. stable deterministic ordering and explicit tie groups;
3. equal-value criterion behavior;
4. duplicate, missing, unknown option, and unknown criterion score rejection;
5. weight validation and Decimal serialization;
6. user-provided, derived, and evidence-backed provenance requirements;
7. sensitivity rank reversal and stable-winner fixtures;
8. endpoint request/response contract;
9. narrative boundary: no generation call unless requested, and generated text cannot alter calculated values;
10. regression suite for existing answering, retrieval, workspace isolation, and evaluation behavior.

Acceptance gate for v1:

- 100% pass rate on hand-calculated scoring and sensitivity fixtures;
- no generated value influences a numeric total without explicit validated input;
- deterministic results are identical across repeated runs;
- API p95 for calculation-only requests stays below 100 ms under the existing service topology, excluding database/network overhead;
- existing deterministic API and web suites remain green.

## 10. Delivery Plan

1. Add pure schemas, scoring, sensitivity, verifier, and unit tests.
2. Add the stateless HTTP service/router and endpoint integration tests.
3. Add optional verified-result narrative generation and tests.
4. Extend the evaluation module with decision-analysis fixtures and latency/provenance metrics.
5. Design a separate, additive persistence proposal only after the stateless slice meets its acceptance gate.

Each implementation step is independently testable and must be reviewed before the next begins.
