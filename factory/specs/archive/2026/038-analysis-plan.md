---
id: 038-analysis-plan
title: AnalysisPlan — evidence-driven analyzer selection
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §12.
- Problem: `scan_project` runs every pipeline unconditionally — proto
  parsing on projects with no proto, runtime loaders when no artifacts
  exist. Cost scales with subsystems, not with evidence.
- Out of scope: skipping *checks* that derive from already-loaded
  models (checks on empty models are cheap); per-analyzer parallelism.
- Review failure: a plan that skips an analyzer whose artifacts exist;
  a plan that hardcodes "run everything" under a flag as the only mode.
- Riskiest assumption: presence rules per analyzer — RESOLVED: derive
  from ArtifactInventory classes (spec 037); each analyzer declares the
  classes it consumes; plan = analyzers whose required classes are
  non-empty. Force-all escape hatch stays for parity.
- Smallest acceptable: `AnalysisPlan` model + `build_plan(inventory)` +
  unit tests per analyzer rule + determinism.

# Context

§12: AnalysisPlan determines applicable analyzers from artifacts
(.proto→grpc, GraphQL schema→graphql, runtime artifacts→runtime,
Terraform→iac-terraform, gateway markers→gateway). Avoid running
subsystems unnecessarily.

# Acceptance Criteria

- `core/plan.py`: `AnalysisPlan` frozen model — `analyzers: tuple[str,
  ...]` (stable ids), `reasons: dict[analyzer, artifact-class]`,
  `skipped: tuple[analyzer, ...]` with reason "no evidence".
- Analyzer registry mapping analyzer-id → required artifact classes,
  covering: openapi, asyncapi, graphql, grpc, routes, clients, runtime,
  gateway, iac, cache, security, reliability, policy, version,
  workspace, ownership, documentation.
- `build_plan(inventory) -> AnalysisPlan` deterministic;
  `force: bool` option returns all analyzers (parity/testing).
- Tests: per-analyzer enable/disable, empty inventory → empty plan,
  determinism, no name-similarity inference.
- pytest/ruff/mypy pass.

# Constraints

- Plan is data, not execution: scan_project consumes it in spec 040.
