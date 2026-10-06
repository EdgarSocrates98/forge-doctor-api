# ADR-0001 — Unified deterministic pipeline over per-domain CLIs

- Status: accepted
- Date: 2026

## Context

Early iterations grew as separate commands (`contract scan`,
`runtime inspect`, `security inspect`, …), each with its own file
walk, parsing and report shape. Cross-domain correlation (routes vs
contracts vs runtime vs infra) was impossible because every command
re-walked the tree and kept its own model — evidence could not be
shared, totals could not be reconciled, and output differed per
command.

## Decision

One pipeline drives everything:
`ProjectContext → discover → EvidenceStore → AnalysisPlan → analyzers
→ models → graph/correlation → checks → DoctorReport`
(`scan_project` in `src/forge_doctor_api/scan.py`).

- Discovery is a single sorted traversal; every analyzer consumes the
  classified inventory, never its own re-walk.
- The `AnalysisPlan` decides which analyzers run from artifact
  evidence — nothing runs without evidence, nothing fabricates a
  domain that had none.
- One `DoctorReport` carries compact `DomainSummary` projections per
  domain plus findings, unknowns, capabilities and stats.

## Consequences

- Cross-domain checks (fanout, twin, drift, impact, migration, cache
  graphs) become possible and cheap.
- Determinism is auditable in one place: one sort order, one
  serialization, one canonical hash surface.
- Domain-specific CLI commands remain as thin lenses over the same
  models; new domains attach to one pipeline instead of a new walk.
- Cost: a scan always runs the full applicable plan — there is no
  "cheap mode" flag. Spec 065's opt-in incremental cache
  (`--incremental`) addresses warm-run cost without changing
  semantics: checks always recompute over cached models.

## Alternatives

- **Keep per-domain CLIs and add a "join" layer** — rejected: joins
  over independently-shaped models multiply schema surfaces and make
  evidence provenance untraceable.
- **Lazy/on-demand domains via flags** — rejected as a default: flag
  permutations break the byte-identical-output guarantee that tests,
  snapshots and gates rely on.
