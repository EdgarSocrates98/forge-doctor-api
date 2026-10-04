---
id: 059-temporal
title: Temporal intelligence — snapshots, deltas, architectural regression
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §70-§72.
- Problem: before/after exists per-scan (`--baseline`), but there is
  no snapshot store, no series, no "architecture regressed since
  release-X" query.
- Out of scope: a time-series database (files under
  `.forge-doctor/snapshots/`); multi-repo temporal (fleet stays
  per-snapshot).
- Review failure: snapshots keyed by wall-clock making them
  non-deterministic; regression findings fabricated from metric
  noise; storing raw payloads in snapshots.
- Riskiest assumption: snapshot identity — RESOLVED: snapshot id =
  analysis content hash + caller-supplied label/tag; clock injected;
  regression = rule-gated comparisons (new BREAKING, new HIGH
  security, removed ops) not score deltas.
- Smallest acceptable: `snapshot save/list/diff/regressions` CLI +
  `SnapshotStore` + `architectural_regressions(prev, cur)` check set
  + tests.

# Context

§70-§72: snapshots over time, deltas, temporal regressions. Builds on
DoctorReport determinism + delta-context (spec 049).

# Acceptance Criteria

- `temporal.py`: `Snapshot{id, label, created_at(injected), report_ref,
  hash}`; `SnapshotStore` file-based under `.forge-doctor/snapshots/`
  (opt-in dir, never auto-created outside explicit save).
- `architectural_regressions(prev, cur) -> tuple[Finding]` — evidence-
  backed classes only: new breaking changes, new high-sev findings,
  removed operations, newly-unknown-required-facts; each carries
  prev/cur evidence refs.
- CLI: `snapshot save <path> --label`, `snapshot list`, `snapshot diff
  <a> <b>` (reuses spec-049 delta), `snapshot regressions <a> <b>`.
- Tests: deterministic ids, regression classes positive+negative,
  reorder-invariance, missing-snapshot errors, offline.
- pytest/ruff/mypy pass.

# Constraints

- Snapshots store compact reports, never payloads.
