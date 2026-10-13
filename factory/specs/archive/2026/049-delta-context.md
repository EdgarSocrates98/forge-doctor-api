---
id: 049-delta-context
title: Delta context — prev/current report diff for incremental handoffs
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §37.
- Problem: a consumer holding yesterday's handoff gets today's full
  bundle again; there is no compact "what changed" projection.
- Out of scope: baseline persistence policy (handoff artifacts are
  already files; the diff takes two reports, not storage decisions);
  semantic equivalence beyond content identity.
- Review failure: a delta that misses findings because it compares
  rendered strings; treating a re-ordered list as a change;
  "resolved" inferred from absence without the prev baseline.
- Riskiest assumption: identity — RESOLVED: findings compare by
  (rule_id + entity + location digest), evidence by sha256,
  operations by operation_id, graph edges by (from,to,kind) tuples —
  documented; name-similarity matching is forbidden.
- Smallest acceptable: `delta(prev_report, cur_report) -> DeltaContext`
  with the §37 field set + tests incl. reordered-identical → empty.

# Context

§37 fields: new findings, resolved findings, changed evidence, changed
operations, changed graph, new unknowns, resolved unknowns. Input:
two DoctorReports (prev hash recorded in handoff).

# Acceptance Criteria

- `handoff/delta.py`: `DeltaContext` frozen model with the §37 field
  set, each a sorted tuple.
- `compute_delta(prev, cur)`; prev is Optional — None → "full" delta
  flagged `initial=True`.
- Identity rules as resolved above; reordering never produces a delta.
- Tests: added/removed/changed findings, evidence churn, graph edge
  add/remove, unknown add/remove, empty delta, determinism.
- pytest/ruff/mypy pass.

# Constraints

- Delta is compact (ids + digests + summaries), never payloads.
