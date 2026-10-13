# Output contract (v1)

The five exported surfaces are frozen for the `0.x` line. This document
is the contract: field names, types, optionality and semantics for
`json`, `jsonl`, `sarif`, `agent` and `report`. Structural tests in
`tests/test_output_contract.py` enforce the shapes described here.

## Evolution rules

- **Additive only within v1.** New optional fields may appear; readers
  must tolerate unknown keys. Existing fields never change type,
  meaning or optionality, and never disappear.
- **Breaking changes require v2.** Renaming a field, changing its
  type, making an optional field required, or altering semantics is a
  `schema_version` bump — never a silent edit.
- `schema_version` is a `MAJOR.MINOR` string (`"1.0"` today). MINOR
  bumps signal additive changes; MAJOR signals a break.
- Every finding id is a stable namespaced check id (e.g. `OAS001`,
  `APISEC011`). Ids are contract — a check that changes meaning gets a
  new id, not a new behavior under the old id.
- Enum values are closed sets; new enum values are additive (MINOR).
- Emitted collections are deterministic: sorted by stable keys,
  byte-identical across runs over identical inputs.

## Shared types

| Type | Shape | Notes |
|---|---|---|
| `Finding` | object | see *Finding object* below |
| `UnknownFact` | `{subject, missing, resolution}` strings | explicit gap |
| `Evidence` | `{kind, source, line?, summary}` | `kind` is an `EvidenceKind` enum value |
| `SourceLocation` | `{path, line?, column?}` | project-relative POSIX path |
| `Severity` | string enum | `CRITICAL` `HIGH` `MEDIUM` `LOW` `INFO` |
| `Confidence` | string enum | `HIGH` `MEDIUM` `LOW` `UNKNOWN` |
| `EvidenceKind` | string enum | `STATIC` `CONFIG` `OBSERVED_METADATA` `RUNTIME` `DERIVED` |

### Finding object

| Field | Type | Optional | Semantics |
|---|---|---|---|
| `id` | string | — | stable namespaced check id |
| `title` | string | — | short human title |
| `description` | string | — | what fired, redacted free text |
| `severity` | Severity | — | impact class |
| `confidence` | Confidence | — | `unknown` ⇒ `unknowns` non-empty |
| `evidence_kind` | EvidenceKind | — | evidence class of the finding |
| `evidence` | `[Evidence]` | — | may be empty; never fabricated |
| `entity_ids` | `[string]` | — | affected entity refs (`kind:domain:identifier`) |
| `source_location` | SourceLocation? | yes | absent ⇒ omitted from SARIF results |
| `remediation` | string? | yes | hint only — never an applied fix |
| `unknowns` | `[UnknownFact]` | — | what would raise confidence |

## `json` — versioned findings envelope

`write_json` → `FindingsExport.to_dict()`:

| Field | Type | Semantics |
|---|---|---|
| `schema_version` | string | `"1.0"` |
| `tool_version` | string | package version |
| `knowledge_versions` | object `{pack: version}` | bundled pack editions used |
| `findings` | `[Finding]` | sorted by `(id, entity_ids, description)` |

## `jsonl` — line-delimited

- Line 1: metadata record `{"_meta": true, "schema_version",
  "tool_version", "knowledge_versions"}`.
- Lines 2+: one `Finding` object each, same order as `json`.
- Terminated by a trailing newline; each line is independently
  parseable JSON.

## `sarif` — SARIF 2.1.0

| Path | Type | Semantics |
|---|---|---|
| `version` | `"2.1.0"` | const |
| `$schema` | string | SARIF schema URL |
| `runs[0].tool.driver.name` | `"forge-doctor-api"` | const |
| `runs[0].tool.driver.version` | string | tool version |
| `runs[0].tool.driver.rules[]` | `{id, name, shortDescription.text, properties{severity, confidence}}` | one rule per distinct finding id, sorted |
| `runs[0].results[]` | `{ruleId, level, message.text, locations, properties{confidence, entity_ids}}` | only findings with `source_location` |
| `runs[0].properties.skipped_no_location` | int | findings omitted for lacking a location |

Findings without `source_location` are **never** forced into a fake
location — they surface in `skipped_no_location` and still appear in
`rules`. `level` maps: critical/high→`error`, medium→`warning`,
low/info→`note`.

## `agent` — compact text

- Line 1: `# schema_version=<v> tool_version=<v>`
- Line 2: `# knowledge_versions=<pack>@<v>,...` (sorted)
- Finding lines: `ID|severity|confidence|subject[:line]|description`
  where `subject` is the first `entity_id`, else the
  `source_location` path, else `-`. Description is whitespace-joined,
  single line.
- Unknown lines: `UNKNOWN|subject|missing`.

Bounded: one line per finding/unknown; no payloads, no wrapping.

## `report` — full `DoctorReport`

`scan --format report` / `DoctorReport.to_dict()`:

| Field | Type | Optional | Semantics |
|---|---|---|---|
| `schema_version` | string | — | report schema (`DOCTOR_REPORT_SCHEMA_VERSION`) |
| `tool_version` | string | — | engine version |
| `knowledge_versions` | `[[pack, version]]` | — | sorted pairs |
| `project` | string | — | root dir name |
| `inventory` | object | — | `ArtifactInventory` |
| `plan` | object | — | `AnalysisPlan` actually executed |
| `analysis_rev` | string? | yes | content hash of inputs |
| `stats` | `AnalysisStats`? | yes | spec-066 counters; `duration_ms`/`allocated_bytes` only under `--stats-timing` |
| `<domain>` | `DomainSummary?` | yes | one per domain (contracts, routes, clients, graph, gateway, mesh, infrastructure, cache, runtime, security, reliability, policies, twin, fanout, migration, impact) — `None` when no evidence |
| `findings` | `[Finding]` | — | sorted, deduped |
| `unknowns` | `[UnknownFact]` | — | explicit gaps |
| `gate_failures` | `[GateFailure]` | — | only populated by `--fail-on` evaluation |
| `diff` | `ContractDiff?` | yes | only with `--baseline` |
| `capabilities` | `[DetectedCapability]` | — | detected capability surface |

Non-canonical fields (`stats.analyzers[].duration_ms`,
`stats.analyzers[].allocated_bytes`) exist only under
`--stats-timing` and are excluded from the snapshot content hash.

## SARIF schema subset

`tests/schemas/sarif-2.1.0-schema.json` is the committed minimal
schema the structural test validates emitted documents against — a
projection of SARIF 2.1.0 covering exactly the surface this tool
emits (not the full upstream schema).
