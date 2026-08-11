---
title: Atlas Product Plan
date: 2026-05-20
participants: [Elena Park, Priya Nair, Marco Silva]
source_type: product_plan
project: Atlas
---

# Atlas Product Plan

## Authentication rollout

Decision: The public authentication rollout is postponed from Q3 to Q4 2026. Status: active. Elena Park approved the postponement on May 20, 2026, and Priya Nair owns authentication readiness.

Reason: The authorization audit trail is incomplete, so the team cannot yet prove who changed a user's permissions or when the change occurred.

Alternative considered: Ship public authentication in Q3 with manual audit exports. Rejected because manual exports can omit permission changes and would create unacceptable compliance risk.

The postponement applies to the public customer rollout. A smaller internal beta may proceed only after Security approves the audit events.

## Search indexing

Decision: PostgreSQL full-text search and pgvector will share the primary database for the MVP. Status: active. Marco Silva owns implementation.

Reason: One database keeps local installation simple and supports transactional document-version retirement.

Alternative considered: Run a separate Elasticsearch cluster. Rejected for the MVP because it adds operational cost without improving the benchmark target.

## Document connectors

Decision: Slack, Notion, and Google Drive connectors are postponed until after the local-file MVP. Status: active. Elena Park owns scope.

Reason: The first release must establish evidence quality on Markdown, text, DOCX, and PDF before adding remote ingestion paths.
