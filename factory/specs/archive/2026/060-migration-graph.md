---
id: 060-migration-graph
title: Migration 2.0 — evidence-backed migration graph and path candidates
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §73-§75.
- Problem: `migrate/` produces per-operation readiness + blockers;
  §73-75 want a migration *graph* — ordering, dependency edges,
  path candidates — all evidence-backed.
- Out of scope: executing migrations, generating code changes,
  cost/time estimation (explicitly roadmap).
- Review failure: ordering edges inferred from operation names;
  "path" candidates that ignore declared dependencies; a graph that
  fabricates edges where only a shared schema exists.
- Riskiest assumption: edge basis — RESOLVED: edges only from
  evidence: shared-schema deps (operation A writes entity X, B reads
  X — from declared request/response schema refs), declared
  versioning relationships, client-impact orderings; shared name or
  path prefix alone → never an edge.
- Smallest acceptable: `MigrationGraph` (nodes=migration units,
  edges=evidence-backed deps) + `migration_paths()` candidates with
  each hop's evidence + blockers preserved + tests.

# Context

§73-§75: migration graph + evidence. Builds on spec-027 migration
model (readiness, blockers, effort class) + graph slices.

# Acceptance Criteria

- `migrate/graph.py`: `MigrationNode{unit_id, readiness,
  blockers}`, `MigrationEdge{from, to, kind: schema-dep|version-dep|
  client-impact, evidence}`.
- `build_migration_graph(model)`; `migration_paths(graph) ->
  tuple[MigrationPath]` — ordered candidates, each annotated with the
  edge evidence and remaining blockers; cycles → reported as unknown
  ordering, never silently broken.
- Tests: schema-dep edge positive+negative (shared schema name alone
  → no edge), cycle handling, path ordering, evidence on every edge,
  determinism.
- pytest/ruff/mypy pass.

# Constraints

- Evidence-required edges; absence → unknown ordering, not a guess.
