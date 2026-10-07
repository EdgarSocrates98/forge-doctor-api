# Public surface inventory

Every public surface, named and classified per
[rc-policy.md](rc-policy.md). The machine-readable counts behind
this document live in [rc-baseline.json](rc-baseline.json)
(`python factory/rc_baseline.py --check` proves the inventory is
not drifting).

## CLI commands (UX + STABLE classes per `cli/catalog.py`)

STABLE: `scan`, `inventory`, `diff`, `fingerprint`, `graph`,
`blast-radius`, `diagnose`, `explain`, `lab`, `contract inspect`,
`contract diff`, `contract compatibility`, `runtime requests`,
`runtime baseline`, `runtime regressions`, `security inspect`,
`reliability inspect`, `reliability path`.

EXPERIMENTAL: `mcp`, `snapshot save`, `snapshot list`,
`snapshot diff`, `snapshot regressions`, `knowledge list`,
`knowledge validate`, `plugins list`, `plugins inspect`,
`plugins verify`.

Human-readable console output is UX class; `--json` output follows
the command's own class.

## SDK exports (STABLE)

`forge_doctor_api.__all__`: `SDK_VERSION`, `AnalysisPlan`,
`ApiHandoffBundle`, `ArtifactInventory`, `Confidence`, `Doctor`,
`DoctorError`, `DoctorReport`, `DomainSummary`, `Evidence`,
`EvidenceKind`, `Finding`, `FindingNotFoundError`, `ForgeHandoff`,
`ForgeReceipt`, `ForgeRef`, `ForgeRequest`, `ForgeResult`,
`Model`, `ProjectContext`, `ProjectUnreadableError`, `Severity`,
`SourceLocation`, `UnknownFact`, `assemble_bundle`, `__version__`.

## MCP surface (STABLE names, EXPERIMENTAL transport)

Tools (`doctor.*`): `doctor.scan`, `doctor.get_service`,
`doctor.get_api`, `doctor.get_contract`, `doctor.get_clients`,
`doctor.get_runtime`, `doctor.get_security`, `doctor.get_reliability`,
`doctor.get_findings`, `doctor.get_unknowns`,
`doctor.get_breaking_changes`, `doctor.get_blast_radius`,
`doctor.get_capabilities`, `doctor.get_graph`, `doctor.get_handoff`,
`doctor.get_operation`, `doctor.explain`.

Resources (`doctor://`): `doctor://service`, `doctor://graph`,
`doctor://unknowns`, `doctor://service/{sid}`,
`doctor://operation/{op}`, `doctor://finding/{ref}`,
`doctor://handoff/{hid}`.

The `mcp` extra itself stays EXPERIMENTAL until the transport story
settles; tool names and resource URIs are STABLE.

## Wire contracts (WIRE)

- `forge-contracts/1` schemas: `entity`, `relationship`,
  `evidence`, `finding`, `capability`, `unknown-fact`,
  `migration-plan`, `remediation-plan`, `handoff`,
  `diagnostic-manifest` — plus the `x-forge-api` extension
  namespace (registry lands with spec 082).
- Forge protocol v2 models: `ForgeRequest` (+ `RequestDelta`),
  `ForgeHandoff`, `ForgeReceipt`, `ForgeResult`, `ForgeRoute`,
  `ForgeRef`, `ForgeCapability`.
- `DoctorReport` JSON + `schema_version` field (output contract
  v1 — additive only).

## Check-id namespaces (STABLE ids)

`OAS`, `COMPAT`, `DRIFT`, `APISEC`, `RELAPI`, `APIREL`, `GQL`,
`GRPC`, `ASYNC`, `APIPERF`, `OBSAPI`, `APITEMP`, `APICACHE`,
`CLIENT`, `POLICY`. An id's meaning never changes in place; new
semantics get a new id.

## Plugin manifest format (STABLE file contract)

`forge-doctor-plugin.toml` / `[tool.forge-doctor.plugin]` in
`pyproject.toml`: keys `id`, `version`, `module`, `doctor_api`,
`capabilities`, `trust_class`, `signature`, `source`; trust classes
`BUILTIN`, `SIGNED`, `APPROVED_LOCAL`, `UNTRUSTED`. Unknown keys
are rejected.

## Internal by default

Everything not listed here is INTERNAL: module layout under
`src/forge_doctor_api/`, analyzer internals, evidence-store file
formats, lab scenario file shapes, `factory/` scripts (tooling,
not product surface).
