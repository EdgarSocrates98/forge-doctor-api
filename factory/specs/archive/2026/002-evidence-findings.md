---
id: 002-evidence-findings
title: Evidence model and Finding contracts
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from §6, §57, §125, §145, §174 of `prompt_evo_inicial.md`.
- Problem: every downstream engine emits findings; the evidence/finding contract must exist first (§225 Phase B).
- Out of scope: concrete checks, check namespaces beyond defining the prefix mechanism, SARIF rendering (spec 030).
- Review failure: finding without declared `evidence_kind`, missing UNKNOWN representation, secrets redaction absent, non-deterministic serialization.
- Riskiest assumption: finding schema is stable enough for SARIF/handoff later — mitigate via `schema_version` + `tool_version` on every export (§174).
- Smallest acceptable: `EvidenceKind`, `Finding`, `UnknownFact`, confidence/severity semantics, redaction utility, tests.

# Context

Phase B (§225). The evidence model (§6) defines five kinds: `STATIC` (source/AST/interface), `CONFIG` (gateway/deployment/policy), `OBSERVED_METADATA` (exported artifacts/inventory), `RUNTIME` (logs/metrics/traces), `DERIVED` (correlation of facts). Every finding must declare its evidence kind — this is the backbone of the low-false-positive and honest-UNKNOWN principles (§1). Secret hygiene (§57) and output redaction (§125) are mandatory from day one.

# Acceptance Criteria

- `EvidenceKind` enum with exactly: `STATIC`, `CONFIG`, `OBSERVED_METADATA`, `RUNTIME`, `DERIVED`.
- `Finding` model carries: stable namespaced check id (e.g. `OAS001`), title, description, `severity`, `confidence`, `evidence_kind`, affected entity refs, `source_location` where applicable, remediation hint, and `unknowns` list.
- `Confidence` and `Severity` levels defined and documented; findings may express UNKNOWN rather than guessing (§145 philosophy).
- `UnknownFact` model records what evidence is missing and what would resolve it.
- Exported payloads carry `schema_version` and `tool_version` (§174).
- Redaction utility removes/masks `Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, `client_secret`, `access_token`, `refresh_token`, passwords, tokens (§57, §125) — applied to finding fields and serialized output.
- Tests: every Finding requires evidence_kind (validation error otherwise); redaction proven on nested structures; serialization deterministic; positive/negative/malformed cases per §202.

# Constraints

- No check implementations — this is the contract layer only.
- Keep finding schema minimal but complete; do not add fields no spec consumes yet.
- Redaction is not optional or configurable-off by default.

# Review Notes

- Check that UNKNOWN is representable as a first-class state, not an exception path.
- Confirm redaction covers dict keys, header-like strings, and URL query params, not just top-level fields.
