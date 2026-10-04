# The-Forger / API Forge boundary

The three products stay separated by responsibility, not by
convention:

```text
forge-doctor-api  deterministic + offline-first + evidence-first
api-forge         agentic engineering (implements changes)
the-forger        orchestration/routing (decides who acts)
```

## What the Doctor owns

Every capability below is a pure function over declared evidence:

- **observe** — discover artifacts, read declared content
- **normalize** — contracts, routes, clients, runtime exports, IaC,
  gateways into one model surface
- **detect** — checks that only fire on evidence
- **measure** — stats, baselines, lab metrics, benchmarks
- **diagnose** — episodes and drift over correlated evidence
- **classify** — capabilities, styles, versions, compatibility classes
- **impact** — blast radius and migration readiness, evidenced
- **report unknowns** — every absent fact is explicit
- **serve context** — `doctor://` refs and compact handoff slices

## What the Doctor never does

Non-goals, enforced by `tests/test_boundary.py` (AST purity) and the
offline test suite:

- no routing — choosing which component acts is The Forger's job
- no scheduling or retries
- no implementation — the Doctor never edits, generates or executes
  code in the analyzed repository (that is API Forge's job)
- no call-outs — no network, no subprocess, no dynamic import, no
  target-code execution on the `handoff/boundary.py` path
- no fabrication — no inference from absence, no hidden uncertainty

## Typed integration

```text
ForgeRequest ──▶ DoctorBoundary.handle() ──▶ ForgeHandoff
        │                                        │
        └── DoctorBoundary.summarize() ──▶ ForgeResult
        └── DoctorBoundary.capabilities() ──▶ ForgeResult
                                              │
                                   consumer ──▶ ForgeReceipt
```

- `ForgeRequest` enters; `ForgeHandoff` (bundle ref + capability and
  unknown refs) and `ForgeResult` (status + refs only) leave.
- `DoctorBoundary` (`handoff/boundary.py`) accepts a `ProjectContext`
  + injected clock. The request's `target` is informational — the
  boundary never re-roots, fetches, or resolves anything external.
- `handoff_to_member_fields` feeds a handoff into fleet aggregation,
  keeping only compact report-equivalent fields — unevidenced model
  fields stay absent and surface downstream as explicit unknowns.

## Boundary module purity

`handoff/boundary.py` imports only context, handoff and protocol
modules plus `scan_project` (deferred). The purity test parses its
AST and rejects: `socket`, `urllib`, `http`, `requests`, `httpx`,
`subprocess`, `importlib` dynamic imports, `exec`/`eval`, and
`os.system`-class calls.
