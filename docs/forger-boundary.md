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
ForgeRequest ──▶ DoctorBoundary.handle() ──▶ ApiHandoffBundle (bounded)
        │      DoctorBoundary.envelope() ──▶ ForgeHandoff
        │      DoctorBoundary.endpoint_dict() ──▶ DoctorEndpoint dict
        │
        └── DoctorBoundary.summarize() ──▶ ForgeResult
        └── DoctorBoundary.capabilities() ──▶ ForgeResult
                                              │
                                   consumer ──▶ ForgeReceipt
```

### Slim ForgeRequest (protocol v2)

| Field | Type | Meaning |
|---|---|---|
| `request_id` | str | consumer-supplied identity |
| `target` | str | informational only — never re-roots the scan |
| `capabilities` | str[] | capability query (detected vs not-evidenced) |
| `context_refs` | str[] | `doctor://` refs the consumer already holds |
| `delta` | RequestDelta? | incremental handoff descriptor |
| `clock` | str? | injected logical clock — never wall time |

`RequestDelta` = `{baseline_ref, changed_files}` — names the prior
analysis to diff against; it never carries report payloads. The
caller resolves `baseline_ref` via the snapshot store and passes the
report as `handle(baseline=...)`; an unresolved baseline degrades to
an explicit `delta` unknown, never a fabricated delta.

`build_request()` emits v2. Parsing accepts protocol versions 1 and
2: v1 `requested_capabilities` maps onto `capabilities` (both keys
together are a conflict error).

### Bounded handoff

`ApiHandoffBundle.bounded()` caps every carried section by
`HANDOFF_BUDGET` (e.g. findings ≤ 512, operations ≤ 2048, graph edges
≤ 2048). Truncation is deterministic — sections are sorted by a
stable key first, then cut — and every truncation appends an
`UnknownFact(subject="handoff:<section>", missing="budget_exceeded:
…")`. Nothing is dropped silently; on V2 bundles the content hash is
recomputed so `handoff_id` stays truthful.

### DeltaContext

`bundle.delta` carries the computed `DeltaContext` —
`analysis_rev_prev`/`analysis_rev_cur`, added/removed/changed sets
per family, plus `baseline_ref`, `changed_files`, and a derived
`protocol_diff` (capability/domain transitions) so a consumer can
answer "did the shape change?" without diffing the lists.

### DoctorEndpoint

`boundary.endpoint_dict(request)` returns The Forger's conceptual
consumption shape, one scan projected four ways:

```text
{request, handoff, capabilities, manifest}
```

- `request` — the echoed request dict
- `handoff` — the typed `ForgeHandoff` over the bounded bundle
- `capabilities` — detected capability entries
- `manifest` — a `forge-contracts/1` `diagnostic-manifest`
  ([forge-protocol.md](forge-protocol.md) wire contract)

- `handoff_to_member_fields` feeds a handoff into fleet aggregation,
  keeping only compact report-equivalent fields — unevidenced model
  fields stay absent and surface downstream as explicit unknowns.

### Facts, never routing instructions

Universal payloads carry observations only. No emitted payload —
`HandoffBundle`, `DiagnosticManifest`, `ForgeResult`, delta —
contains orchestration keys (`next_tool`, `route_to`, `schedule`,
`delegate`, `invoke`); the conformance suite scans every emitted
shape recursively for them. Who acts on a handoff is the consumer's
decision, outside the Doctor's contract surface.

## Boundary purity (package-wide)

`tests/test_boundary.py` enforces the boundary rules at the AST
level across **all of `src/forge_doctor_api/`**:

- import roots banned everywhere: `socket`, `urllib`, `http`,
  `requests`, `httpx`, `subprocess`, `shutil`, `ctypes`, `pickle`,
  `os`
- bare-name call bans: `exec`, `eval`, `compile`, `__import__`,
  `system`, `popen`, `fork`, `spawn*`, `execv*`
- attribute bans: `os.system`-class, `pickle.load*`, `ctypes.*`
  loaders, `importlib.import_module`
- `importlib` is allowlisted only for enumerated safe uses:
  `core/stats.py` (own-package catalog lazy-load),
  `knowledge/loader.py` (package resources), `lab/capabilities.py`
  (`find_spec` detection only), `plugins/registry.py` (entry-points
  metadata), `plugins/trust.py` (trust-gated plugin import)
- `handoff/boundary.py` itself is stricter still — no `getattr`, no
  `importlib` text at all

`handoff/boundary.py` imports only context, handoff and protocol
modules plus `scan_project` (deferred) — it never routes, schedules,
retries, implements, or calls out.
