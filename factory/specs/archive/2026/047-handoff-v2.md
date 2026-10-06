---
id: 047-handoff-v2
title: Handoff V2 — refs + hashes + receipts over the compact bundle
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §24, §26, §28.
- Problem: `assemble_bundle` already emits a compact bundle
  (schema_version, findings, breaking changes, impacted clients,
  runtime/security/reliability summaries, remediation candidates,
  unknowns, knowledge versions) but has no content hashes, no
  ForgeReceipt linkage, no handoff identity chain — §24's "Handoff V2
  over payload V1".
- Out of scope: transport, signing/attestation (spec 069); changing
  bundle v1 schema (V2 is additive: `handoff_version=2` + new fields).
- Review failure: hashes computed over non-deterministic serialization;
  a receipt that cannot link back to the analysis revision; payloads
  creeping in (schemas, spans, source).
- Riskiest assumption: hash inputs — RESOLVED: hash the canonical
  `to_json(sort_keys)` bytes of the pre-hash payload (hash field
  excluded), sha256; document input in code.
- Smallest acceptable: `handoff_version=2` bundle carrying handoff_id,
  artifact/evidence/handoff sha256 refs, ForgeHandoff wrapper, receipt
  builder — + tests.

# Context

§24: Handoff V2 favors ids/hashes/summaries/evidence-refs/graph-slices/
unknowns/findings/affected-operations/constraints/capabilities over raw
sources/schemas/traces/configs. §28: content hashing + receipts
support analysis revision/hash, handoff identity, consumer identity,
implementation-result linkage.

# Acceptance Criteria

- `bundle.py` gains `handoff_version: Literal[1,2]`; V2 adds
  `handoff_id` (deterministic, from content hash), `analysis_rev`
  (sha256 of report), per-domain `*_sha256` refs, `context_refs`
  (doctor:// ids from spec 048), `capabilities`.
- `build_receipt(handoff, consumer, result)` → ForgeReceipt (spec 046).
- V1 unchanged and still emitted when `handoff_version=1`.
- Tests: hash stability across runs/machines (fixed clock), receipt
  linkage, V1/V2 parity on shared fields, determinism.
- pytest/ruff/mypy pass.

# Constraints

- Compact only — reuse the existing bundle's redaction/summary policy.
