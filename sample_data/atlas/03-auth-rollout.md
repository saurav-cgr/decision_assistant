---
title: Atlas Authentication Rollout Decision Memo
date: 2026-07-08
participants: [Priya Nair, Jonah Reed, Elena Park]
source_type: decision_memo
project: Atlas
---

# Atlas Authentication Rollout Revision

## Decision

Decision: Begin the employee-only authentication beta on July 22, 2026. Status: active. Priya Nair owns the rollout, and Jonah Reed owns security approval.

This accepted revision supersedes the June 12 proposal to begin the internal beta on July 15. The date moved by one week so all six authorization audit events can complete integration testing.

Public customer authentication remains postponed to Q4 2026. The internal beta does not supersede the May 20 public-rollout postponement.

## Reason and evidence

The authorization audit trail must record the actor, subject, previous value, new value, and timestamp for every role or permission change. Five events pass; the permission-override event still fails the replay test.

## Alternatives considered

Keep the July 15 date and disable permission overrides during beta. Status: rejected. The team would not learn whether the complete authorization path works under realistic use.

Cancel the internal beta and wait for Q4. Status: rejected. The team chose a one-week delay because limited employee evidence is useful before public release.

## Exit criteria

Security approval requires all six event tests, no critical login defects, and a documented rollback. A separate decision is required before any customer receives authentication access.
