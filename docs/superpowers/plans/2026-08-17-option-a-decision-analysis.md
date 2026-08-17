# Option A Decision Analysis Implementation Plan

**Design:** `docs/superpowers/specs/2026-08-17-option-a-decision-analysis-design.md`
**Status:** Proposed

## Guardrails

- Preserve the current decision-memory guarantees: workspace isolation, citation verification, corpus-profile guards, abstention, and offline deterministic tests.
- Keep decision mathematics in backend Python; React may render values but must not recalculate ranking truth.
- Use no new dependency in the first vertical slice.
- Do not make a database schema change or persist analysis runs without separate approval.
- Do not treat LLM-generated scores or confidence as final authority.
- Keep each hand-written source file below 500 lines.

## Step 1 — Specification and boundary agreement

Create the proposed Option A design and this delivery plan. The first release is a stateless weighted-sum API with sensitivity analysis; TOPSIS, AHP, automatic retrieval-to-score extraction, persistence, and UI are deferred.

**Verification:** architecture is compatible with the present FastAPI modular monolith, Pydantic provider contracts, evidence verification, and evaluation structure; no source or schema files change.

## Step 2 — Pure decision-analysis domain

Add `api/src/decision_assistant/decision_analysis/` with:

- `schemas.py` for the request/result contracts;
- `scoring.py` for Decimal normalization, weighted-sum totals, ties, and sensitivity;
- `verifier.py` for input/result invariants;
- unit tests containing hand-calculated fixtures.

**Verify:** focused unit tests in Docker. No routes, providers, or database models change.

## Step 3 — Stateless API vertical slice

Add `service.py`, `router.py`, route registration, and endpoint tests for `POST /api/v1/decision-analyses`.

**Verify:** focused API tests plus relevant existing question/retrieval regression tests. No schema migration.

## Step 4 — Optional narrative generation

Add a schema-constrained, verified-result-only narrative path. It must fail closed to the deterministic result and cannot alter calculations.

**Verify:** fake-provider tests prove no narrative request contains unverified inputs and no provider response changes scores/ranks.

## Step 5 — Evaluation and release decision

Add decision-analysis fixtures and metrics to the existing evaluation approach; measure deterministic correctness, API latency, provenance coverage, and sensitivity outcomes. Decide whether persistence, retrieval-assisted scoring, TOPSIS, or a user interface is justified.

**Verify:** full relevant API suite and a documented benchmark result.
