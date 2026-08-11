---
title: Atlas Architecture Sync
date: 2026-06-12
participants: [Priya Nair, Marco Silva, Jonah Reed]
source_type: meeting_notes
project: Atlas
---

# Atlas Architecture Sync

## Proposed internal authentication beta

Proposal: Start an employee-only authentication beta on July 15, 2026, using the existing OpenID Connect provider. Status: proposed. Priya Nair is the decision owner.

Reason: An internal beta would exercise login, session expiry, and role changes while limiting customer exposure. Security approval of authorization audit events remains the entry condition.

Alternatives considered: Wait for the Q4 public rollout, or build password authentication in Atlas. The team rejected password authentication because it would create new credential-storage responsibility. Waiting for Q4 remains a fallback, not the preferred option.

This proposal does not reverse the May decision: public customer authentication remains postponed to Q4.

## Passage chunk size

Decision: Begin retrieval experiments with chunks near 500 tokens and preserve source boundaries. Status: proposed. Marco Silva owns evaluation.

Reason: The team needs benchmark evidence before fixing a final chunk size.

## Retention

Decision: Keep superseded document versions for traceability while excluding them from normal retrieval. Status: active. Jonah Reed approved the policy.
