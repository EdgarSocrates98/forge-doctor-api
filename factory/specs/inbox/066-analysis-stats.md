---
id: 066-analysis-stats
title: Doctor observability — analysis stats + explain surfaces
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §91-§93.
- Problem: the engine is a black box — which analyzers ran, how many
  artifacts each consumed, where unknowns concentrate is invisible.
  §91-93 want stats + explain surfaces.
- Out of scope: telemetry/reporting anywhere external (stats live in
  the report, opt-out flag only); real-time dashboards.
- Review failure: stats that leak wall-clock nondeterminism into the
  deterministic report (must be a separate optional section);
  explain output that restates the finding without its evidence.
- Riskiest assumption: determinism boundary — RESOLVED: stats live in
  `DoctorReport.stats` as an *optional* section excluded from the
  canonical hash (wall-time fields marked non-deterministic;
  artifact/analyzer counts are deterministic and stay in the core
  report).
- Smallest acceptable: per-analyzer {ran, artifacts_consumed,
  findings_emitted, unknowns_emitted} + `explain` CLI command
  (finding → full evidence chain + rule description + unknowns) +
  tests.

# Context

§91-§93: stats + explainability. Deterministic fields and
non-deterministic timing are separated explicitly.

# Acceptance Criteria

- `DoctorReport.stats`: `AnalysisStats{analyzers:
  tuple[AnalyzerStat{analyzer, ran, artifacts, findings, unknowns}],
  totals}` — deterministic fields always emitted; `durations` only
  under `--stats-timing` and excluded from report hash/determinism
  test.
- CLI `explain <finding-id>`: rule description (knowledge pack),
  evidence chain, confidence, unknowns, next-evidence suggestions —
  same content via SDK `explain()` and MCP `doctor.explain`.
- Tests: stat counts match reality, determinism unaffected,
  explain on known + unknown finding id.
- pytest/ruff/mypy pass.

# Constraints

- Timing never in the canonical/hashed report surface.
