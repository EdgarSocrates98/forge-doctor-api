You are implementing Loop Factory spec `002-evidence-findings`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\002-evidence-findings.md`
        Spec hash: `5328ed5b041c5863bf242f4d41a2c089336fb8f36318124ce17806e6d1c32ded`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
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
