---
id: 074-forge-contracts-conformance
title: forge-contracts/1 wire conformance — shared vocabulary adapter
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions from stabilization prompt Phase D +
  §24-§26.
- Problem: two Forge doctors must speak one wire language. Today only
  the Data Doctor ships `forge-contracts/1`; the API Doctor emits a
  parallel vocabulary.
- Out of scope: importing `forge_doctor_data` (PROHIBITED — D.1);
  extracting a shared kernel package (§26 — deferred until both sides
  prove the same wire semantics); changing ServiceGraph identity rules.
- Review failure: an adapter that claims conformance but emits
  domain-specific shapes into core fields; `x-forge-api` leaking into
  required fields; conformance tests that re-import the sibling repo.
- Riskiest assumption: the canonical schema can be vendored without
  drift — RESOLVED: schemas are pure-data JSON Schema dicts; we vendor
  them verbatim under `contracts/` marked as the shared wire source of
  truth, with a header noting origin and version.
- Smallest acceptable: `contracts/` package (wire models + version
  negotiation + vendored schemas) + `contracts/adapters.py`
  (core models → forge-contracts/1 dicts, `x-forge-api` namespace for
  operation/protocol/client-impact/run-time specifics) + a
  dependency-free schema validator covering required/enum/type/
  additionalProperties + conformance tests against canonical fixtures.

# Context

Phase D. Canonical shapes (vendored from forge-contracts/1):
Finding{check_id,title,severity∈error|warning|info|pass,category,
message,...}, Entity{id,kind,domain,identifier,name,file,line,attrs},
Relationship{src,dst,kind,evidence_kind,attrs}, Evidence{ref,kind,
source,detail}, Capability{id,domain,status,confidence,evidence_refs},
UnknownFact{subject,kind,reason,source,detail}, RemediationPlan,
MigrationPlan, HandoffBundle{tool,project,summary,findings,entities,
relationships,capabilities,plans,unknowns}, DiagnosticManifest. Every
object carries `contract_version: "forge-contracts/1"`. `x-*` keys are
domain extensions that survive round trips.

# Acceptance Criteria

- `src/forge_doctor_api/contracts/`: `version.py` (ContractVersion,
  negotiate, within_range, CURRENT=forge-contracts/1), `models.py`
  (frozen wire dataclasses with strict null/extension semantics),
  `schemas.py` (vendored canonical JSON Schemas), `adapters.py`
  (Finding/Entity/Relationship/UnknownFact/Capability/HandoffBundle
  builders from core models), `validate.py` (minimal validator:
  required fields, enum, type, x-* passthrough).
- API-specific fields (entity_ids, protocol, operation identity,
  compat class, runtime signals) travel under `x-forge-api` —
  never in core fields.
- Severity map: CRITICAL/HIGH→error, MEDIUM→warning, LOW/INFO→info;
  confidence lowercased; entity id decomposes to kind/domain/identifier.
- `tests/test_contracts.py`: canonical fixture decodes; adapter output
  validates against every schema; round-trip preserves x-* extensions;
  severity/enum violations raise; a `DoctorReport` produces a
  conforming `handoff` payload + `diagnostic-manifest`.
- `docs/forge-protocol.md` documents the wire contract, the
  x-forge-api extension registry, and the no-import boundary.
- pytest/ruff/mypy pass; no `forge_doctor_data` import anywhere in
  src/ or tests/ (AST-checked).

# Constraints

- Zero new runtime deps. Deterministic ordering everywhere.
- `ServiceGraph` stays API-specific (§5) — only the wire vocabulary
  is shared.
