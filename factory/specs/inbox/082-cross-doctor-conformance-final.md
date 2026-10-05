---
id: 082-cross-doctor-conformance-final
title: Cross-doctor conformance final — canonical fixtures, x-forge-api registry, extraction doc
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 2 and cross-cutting items §3/§4/§6/§19/§20.
- Problem: `forge-contracts/1` conformance exists per-model, but the
  cross-doctor promise lacks a canonical fixture corpus that any
  implementation can parse, a registered `x-forge-api` extension
  namespace, and a written rule for when a field graduates to the
  universal contract. DeltaContext is on the wire but lacks explicit
  client/runtime/delta categories tests.
- Out of scope: extracting a shared Python package with the Data
  Doctor (prompt explicitly defers); adding contract majors;
  orchestration fields (they are banned, §4).
- Review failure: fixtures that only exercise happy paths; an
  x-forge-api registry that is a list without semantics; a
  conformance suite that passes because it asserts nothing a wrong
  implementation would fail.
- Riskiest assumption: canonical fixtures can stay dependency-free
  while still catching semantic drift — RESOLVED: fixtures pin both
  the wire JSON and the decoded invariants (required-null errors,
  extension round-trip, enum behavior).
- Smallest acceptable: fixture pack + decoder conformance tests +
  x-forge-api registry doc/test + extraction criteria doc +
  DeltaContext category coverage.

# Context

Phase 2. Existing: `contracts/models.py`, `validate.py`,
`schemas.py`, `adapters.py`, `version.py`; one vendored Data Doctor
handoff fixture (`tests/fixtures/contracts/`); `handoff/delta.py`
already emits DeltaContext on the wire. Missing: canonical
per-model fixture pack, explicit x-forge-api registry, forward-compat
and null-semantics conformance matrices, no-orchestration-fields
proof, extraction criteria.

# Acceptance Criteria

- `tests/fixtures/contracts/canonical/` holds one canonical JSON
  fixture per contract type: entity, relationship, evidence,
  finding, capability, unknown-fact, migration-plan,
  remediation-plan, handoff, diagnostic-manifest. Each fixture
  exercises required fields, an optional field set and omitted, and
  at least one `x-*` extension.
- `tests/test_contract_conformance.py` (extend or new file)
  round-trips every canonical fixture through `from_dict` /
  `to_dict` byte-identically, and validates each against
  `FORGE_CONTRACT_SCHEMAS` via `contracts.validate`.
- Null-semantics matrix test: for every model — required scalar
  missing and required scalar `null` both raise; missing/null/empty
  collection decodes to empty; optional scalar missing/null decodes
  to `None` and is omitted on output.
- Forward-compat tests: unknown `x-*` keys survive a round trip;
  unknown non-x keys are rejected by strict protocol parsers;
  extension payloads do not change universal semantics (a finding
  with and without `x-forge-api` decodes to the same universal
  fields).
- API-specific root fields outside `x-forge-api`: a test asserts
  `report_handoff` emits no non-`x-*` API-specific keys at the
  bundle root, and universal decoders ignore `x-forge-api` content.
- `docs/x-forge-api.md`: registry of every `x-forge-api` key
  emitted (name, payload shape, optionality, producer), matching
  `adapters.py` reality; a test asserts registered keys ⊆ emitted
  keys and emitted keys ⊆ registered keys.
- `docs/shared-contract-extraction.md`: extraction criteria (same
  semantics both doctors, same lifecycle, same null semantics, same
  version negotiation, same forward compatibility) and the explicit
  decision to keep vendoring for now.
- DeltaContext conformance: test covering changed_files echo,
  capability/domain transitions, finding/operation/unknown delta
  categories; document the categories in `docs/handoff.md` or the
  delta model docstring stays the contract.
- No orchestration fields: a test asserts no universal payload
  contains `next_tool`, `route_to`, `schedule`, `delegate`,
  `invoke` keys (recursive scan over `to_dict` of every emitted
  bundle type).
- `docs/forger-boundary.md` (or boundary doc): endpoint_dict /
  request contract shape documented — the Doctor hands over facts,
  never routing instructions.
- pytest/ruff/mypy pass.

# Constraints

- Fixtures are data, not code; no generator scripts needed.
- Do not modify `forge-contracts/1` model fields — additive
  extensions only via `x-forge-api`.
- Vendored fixture sha256 in `PROVENANCE.md` stays truthful.
