# Forge Protocol

Typed, versioned contracts for cross-product exchange:

```
forge-doctor-api  = deterministic + offline + evidence-first (producer)
api-forge         = agentic engineering (consumer)
the-forger        = orchestration/routing (consumer)
```

`forge_doctor_api.handoff.protocol` — `PROTOCOL_VERSION = 1`.

## Models

| Model | Fields | Role |
|---|---|---|
| `ForgeRequest` | request_id, target, requested_capabilities, clock | consumer → Doctor |
| `ForgeHandoff` | handoff_id, bundle_ref, analysis_rev, refs, capabilities, unknowns | Doctor → consumer |
| `ForgeRef` | ref_id, kind, entity?, sha256?, summary | typed reference |
| `ForgeCapability` | name, status, unknowns | observed capability |
| `ForgeReceipt` | analysis_rev, handoff_id, consumer, result_link | consumer ack → Doctor |
| `ForgeResult` | status, summary, refs | typed result surface |
| `ForgeRoute` | route_id, source, destination, capability | routing record |

## Rules

- **Strict parse** — `*.parse(dict)` rejects unknown fields unless they
  use the `x-*` extension namespace; `ProtocolError` on violations.
- **Version check** — `protocol_version` must equal 1.
- **Deterministic builders** — `build_request`, `build_handoff`,
  `build_receipt`, `build_result`; clocks are injected, never wall time.
- **Unknowns are typed refs** — `ForgeHandoff.unknowns` carries
  `ForgeRef(kind="unknown")`; nothing fabricates a capability.
- **Receipts link back** — `ForgeReceipt.analysis_rev` binds the
  consumer's result to the exact analysis revision it consumed.

## Handoff V2

`assemble_bundle(handoff_version=2, report=report)` adds to the V1
bundle: `handoff_id` (sha256 of the V1 body — deterministic across
machines), `analysis_rev` (report content hash), per-domain
`domain_sha256`, `doctor://` `context_refs`, and `capabilities`.

## forge-contracts/1 — the shared wire vocabulary (spec 074)

The cross-doctor wire contract is `forge-contracts/1`: the same
vocabulary the Data Doctor emits, so The Forger consumes either doctor
through one `DoctorEndpoint` shape (`request → handoff envelope`).

`forge_doctor_api.contracts` vendors the canonical contract —

| Module | Contents |
|---|---|
| `version.py` | `ContractVersion` (`family/major`), `negotiate`, `within_range`; `CURRENT = forge-contracts/1` |
| `models.py` | wire dataclasses: `Finding`, `Entity`, `Relationship`, `Evidence`, `Capability`, `UnknownFact`, `MigrationPlan`, `RemediationPlan`, `HandoffBundle` (`bounded()` truncation → recorded `UnknownFact`s), `DiagnosticManifest` |
| `schemas.py` | the published JSON Schemas (`FORGE_CONTRACT_SCHEMAS`) — vendored pure data |
| `validate.py` | dependency-free validator: required keys, enums, primitive types, nested items; `x-*` always allowed |
| `adapters.py` | core models → wire payloads; `report_handoff(report)` → conforming `handoff`; `report_manifest(report)` → `diagnostic-manifest` |

Contract rules (frozen): required scalars reject missing **and**
explicit `null`; collections treat missing/`null`/`[]` alike; optional
scalars emit absent, never `null`; every object carries
`contract_version: "forge-contracts/1"`; `x-*` keys are the
forward-compat channel and round-trip untouched.

**`x-forge-api` extension registry** — API-domain fields travel under
`x-forge-api`, never reshaped into core wire fields:

| Field | On | Content |
|---|---|---|
| `entity_ids` | finding | affected canonical entity ids |
| `evidence_refs` | finding | evidence pointers (`path:Lnn`) |
| `unknowns` | finding, relationship | `{subject, missing, resolution}` triples |
| `evidence_ids` | relationship | typed evidence refs from `EdgeExport` |
| `analysis_rev`, `schema_version` | handoff, manifest | analysis revision + report schema |

Severity maps `CRITICAL|HIGH→error`, `MEDIUM→warning`, `LOW|INFO→info`;
confidence lowercases to `high|medium|low|unknown`; entity ids decompose
to `kind`/`domain`/`identifier` via the canonical
`{kind}:{domain}:{identifier}` grammar.

**Boundary:** no `forge_doctor_data` import anywhere in `src/` or
`tests/` (AST-enforced by `test_contracts.py`). The doctors share the
published contract — schemas vendored as pure data — while internals
(`ServiceGraph`, adapters, engine models) stay independent. A shared
kernel package is deferred until both doctors prove identical wire
semantics, lifecycle, and compatibility expectations (§26).
