# CLI reference

Entry point: `forge-doctor-api` (console script →
`forge_doctor_api.cli:main`). All commands are deterministic and offline.
Global exit codes: `0` success · `1` gate failure · `2` usage error ·
`3` not implemented (reserved for placeholders).

```text
forge-doctor-api --help      list commands
forge-doctor-api --version   print version and exit
```

## scan

```text
forge-doctor-api scan TARGET [--fail-on CATS] [--baseline PATH]
                        [--policy PATH] [--format FMT] [--out FILE]
                        [--incremental] [--stats-timing]
```

Runs every pipeline: OpenAPI/AsyncAPI/GraphQL/gRPC parsing and checks,
security, reliability, client scan, runtime ingestion + performance,
policies, and (with `--baseline`) the semantic contract diff.

| Option | Meaning |
|---|---|
| `--fail-on` | Comma-separated gate categories: `breaking`, `security`, `policy`. |
| `--baseline` | Old contract file/dir — required when `breaking` is enabled. |
| `--policy` | Extra policy file/dir merged into evaluation. |
| `--format` | `console` (default), `json`, `jsonl`, `sarif`, `agent`, `report` (full DoctorReport). |
| `--out` | Write export to a file instead of stdout. |
| `--incremental` | Reuse analyzer-level models from `.forge-doctor/cache/` keyed by artifact sha256 + analyzer + tool version + config. Findings always recompute; output is byte-identical to a cold scan. |
| `--stats-timing` | Record per-analyzer `duration_ms`/`allocated_bytes` in `report.stats` — opt-in, excluded from the canonical hash. |

`report.stats` always carries deterministic per-analyzer counters
(`ran`, `artifacts`, `findings`, `unknowns`) plus totals — no flag
needed. The cache dir is created only by `--incremental`; a plain
scan never writes `.forge-doctor/`.

Gate semantics: `breaking` fails on any `BREAKING` diff change;
`security` fails only on HIGH-confidence `APISEC###` findings; `policy`
fails on `POLICY###` violations. UNKNOWN-confidence findings never block.
Exit `1` when a category fires, `2` when misconfigured (e.g. `breaking`
without a baseline).

## inventory

```text
forge-doctor-api inventory TARGET [--json]
```

Fleet intelligence over a workspace (`forge-doctor-api.workspace.yaml`)
or a single repo (synthesized one-member workspace). Prints the §110
questions — public APIs, unowned APIs, unauthenticated operations,
deprecated versions, regressing endpoints, shared external APIs — plus
complexity signals and deprecation readiness. Missing members produce
UNKNOWN answers, not silence.

## diff

```text
forge-doctor-api diff OLD NEW [--semantic] [--json] [--pr] [--clients DIR]
```

Semantic contract diff. Emits typed `ChangeEvent`s (operation/element
granularity — never file-level). `--pr` adds the six-counter PR summary;
`--clients DIR` feeds blast radius into the summary.

## contract

```text
forge-doctor-api contract diff OLD NEW           contract-level diff
forge-doctor-api contract compatibility OLD NEW  compatibility classification only
forge-doctor-api contract inspect TARGET         inventory of parsed contract documents
```

`inspect` prints document metadata only (title, version, operation
counts, source paths) — never schema bodies. Exit `2` when TARGET
contains no inspectable contract.

## fingerprint

```text
forge-doctor-api fingerprint FILE|DIR
```

Prints the semantic fingerprint — stable across formatting, ordering,
and comment changes (§180). Used by `BackwardCompatibilityBaseline`.

## graph

```text
forge-doctor-api graph TARGET [--json]
```

Merged service graph: contract entities, discovered routes, and client
call sites in one `ServiceGraph`. Console prints entity/edge counts;
`--json` emits the graph.

## blast-radius

```text
forge-doctor-api blast-radius OLD NEW [--clients DIR] [--json]
```

Change impact: which operations changed, which client call sites hit
them, which services/paths are affected. Only evidenced nodes appear —
unresolvable subjects yield `UnknownFact`s.

## runtime

```text
forge-doctor-api runtime requests DIR    normalized per-request executions
forge-doctor-api runtime baseline DIR    per-endpoint performance baselines
forge-doctor-api runtime regressions DIR baseline vs observed regressions
```

DIR contains runtime artifacts (OTLP JSON, access logs). See
[runtime-evidence.md](runtime-evidence.md).

## security inspect

```text
forge-doctor-api security inspect DIR [--json]
```

Passive security evidence and APISEC001–010 candidates: unauthenticated
object-id routes, admin ops without authz evidence, anonymous sensitive
flows, missing rate limits, unrestricted collections, SSRF-shaped params,
sensitive-field exposure, deprecated-but-reachable ops.

## reliability

```text
forge-doctor-api reliability inspect DIR [--json]
forge-doctor-api reliability path DIR --hop NAME [--retry SCOPE=N] [--timeout SCOPE=D]
```

`inspect` lists timeouts, retries, idempotency, rate limits, health,
SLOs from config evidence. `path` walks a declared call chain and shows
the effective timeout/retry per hop — including retry amplification.

## diagnose

```text
forge-doctor-api diagnose TARGET [--before DIR] [--json]
```

Builds `ApiIncidentEpisode`s: runtime regression findings + config
change events + call-path evidence, producing ranked *candidate causes*
(STATIC / RUNTIME / DERIVED — DERIVED only when a config change and a
runtime signal agree on the same hop). Wording is always "candidate" —
never "confirmed".

## explain

```text
forge-doctor-api explain DIR FINDING [--json]
```

Matches a finding by id or subject token and renders its evidence chain,
classification, unknowns, and remediation. Ambiguous matches print a
disambiguation list.

## lab

```text
forge-doctor-api lab [TARGET] [--json] [--no-record]
```

Runs the Forge Lab corpus (golden + adversarial fixtures), reports
precision/recall per finding family, and writes a run record to
`factory/runs/` unless `--no-record`.

## snapshot

```text
forge-doctor-api snapshot save [TARGET] [--label L]
forge-doctor-api snapshot list [TARGET]
forge-doctor-api snapshot diff A B [--target DIR]
forge-doctor-api snapshot regressions A B [--target DIR]
```

Temporal intelligence (spec 059): `save` scans TARGET and stores a
compact report under `.forge-doctor/snapshots/` — the directory is
created only by an explicit save. Snapshot ids are content hashes
(deterministic, reorder-invariant); `created_at` is injected.
`diff` reuses the spec-049 delta context; `regressions` emits
evidence-backed findings for new breaking changes (APITEMP001), new
high-severity findings (APITEMP002), removed operations (APITEMP003),
and newly-unknown required facts (APITEMP004), each carrying
previous + current snapshot evidence refs.

## knowledge

```text
forge-doctor-api knowledge list [DIRS...] [--target DIR]
forge-doctor-api knowledge validate DIR
```

Pack lifecycle (spec 064): `list` shows every discovered pack manifest
with lifecycle status (`active`, `skipped-incompatible`,
`conflict-shadowed`, `rejected`) plus the builtin pack pinned to the
engine version. Precedence: explicit dirs > project
`.forge-doctor/knowledge/` > builtin; the first entry in precedence
order wins a duplicate-id conflict deterministically. `validate`
strict-parses one `forge-doctor-knowledge.toml` — malformed manifests
exit 2 listing every error, incompatible ones exit 1.

## plugins

```text
forge-doctor-api plugins list [DIR]
forge-doctor-api plugins inspect MANIFEST
forge-doctor-api plugins verify DIR
```

Plugin lifecycle (specs 053–054): `list` shows discovered plugin
manifests with status; `inspect` prints one manifest's declared
surface; `verify` runs the offline conformance harness — untrusted
plugin code is never imported (see
[ADR-0004](adr/ADR-0004-untrusted-plugins.md)).

## mcp

```text
forge-doctor-api mcp [TARGET] [--transport stdio]
```

Serves the Doctor over MCP (requires the `mcp` extra — see
[docs/mcp.md](mcp.md)). Every `doctor.*` tool is a projection over the
SDK facade; `doctor://` resources resolve through the context broker.
