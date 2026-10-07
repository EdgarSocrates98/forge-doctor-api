# `x-forge-api` extension registry

The `forge-contracts/1` wire vocabulary is universal. API-Doctor
particulars travel only under the `x-forge-api` extension key — a
consumer that does not know them can ignore them and lose nothing
about the universal payload. Extension rules: additive only, optional
always, semantics-neutral (a finding means the same thing with or
without `x-forge-api`), and preserved verbatim on round trips.

The machine-readable key set below is contract-checked —
`tests/test_contract_conformance.py::test_x_forge_api_registry_matches_emitted_keys`
fails if `contracts/adapters.py` emits a key not registered here or
drops one that is.

```json
{"keys": [
  "analysis_rev",
  "entity_ids",
  "evidence_ids",
  "evidence_refs",
  "schema_version",
  "unknowns"
]}
```

## Keys

| Key | Emitted on | Payload | Notes |
| --- | --- | --- | --- |
| `analysis_rev` | `handoff` root, `diagnostic-manifest` root | string | analysis revision the bundle was produced from; lets consumers address deltas to a known baseline |
| `entity_ids` | `finding.x-forge-api` | string[] | canonical `kind:domain:identifier` entity ids the finding is bound to |
| `evidence_ids` | `relationship.x-forge-api` (from `EdgeExport`) | string[] | evidence record ids supporting the edge |
| `evidence_refs` | `finding.x-forge-api` | string[] | `file[:Lline]` references backing the finding |
| `schema_version` | `handoff` root | string | `DoctorReport` output-contract version (e.g. `"1.0"`), independent of the contract family |
| `unknowns` | `finding.x-forge-api`, `relationship.x-forge-api` | object[] | `{"subject","missing","resolution"}` — evidence gaps attached to the specific item |

## Rules for new keys

- A new key is additive: registering it must not change the meaning
  of any existing key or any universal field.
- Keys stay optional forever — a payload without them is still
  conforming.
- Prefer one namespaced key with a small object over several flat
  keys; flat keys are for scalars and id lists.
- The registry gate is bidirectional: emitting an unregistered key
  or registering an unemitted key fails the suite.
