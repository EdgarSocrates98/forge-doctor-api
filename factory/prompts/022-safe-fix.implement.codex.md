You are implementing Loop Factory spec `022-safe-fix`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\022-safe-fix.md`
        Spec hash: `07d4ffc4ff64f81c54bb2bcdb8794a358eb2e493b7e444bfd3ba12402e5ac5aa`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Codex subagents when work splits cleanly. Ask explicitly before spawning. Keep final answer terse with files changed and checks run.

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

- Owner: project owner; decisions sourced from §104, §5 (Remediation model).
- Problem: every suggested fix must carry a risk class so nothing dangerous is implied safe (§225 feeds handoff bundles later).
- Out of scope: generating/applying patches — this spec classifies remediation *candidates* only.
- Review failure: auth/breaking/rate-limit fixes classed below MANUAL_ONLY, missing justification per class.
- Riskiest assumption: classification table completeness — RESOLVED: §104 provides the complete three-class table; unmapped fix types default MANUAL_ONLY (default-deny, deterministic from table).
- Smallest acceptable: `Remediation` model + rule table for §104 examples + classifier + findings linkage.

# Context

Safe-fix classification (§104): `SAFE` (missing explicit OpenAPI metadata, deprecated config rename, documentation field, simple spec normalization); `REVIEW_REQUIRED` (timeout, retry, cache, pagination defaults); `MANUAL_ONLY` (auth, authorization, breaking contract, gateway routing, TLS, rate limits, schema removal). Unknown/unmapped → MANUAL_ONLY default.

# Acceptance Criteria

- `Remediation` model (from §5) extended: proposed change, target, classification, justification, evidence refs.
- Rule table implementing §104's three classes and their listed members; unmapped types default MANUAL_ONLY.
- Classifier runs over existing findings → attaches remediation candidates with class + justification.
- Conservative guards: any fix touching auth/authorization/breaking/gateway-routing/TLS/rate-limits/schema-removal is always MANUAL_ONLY regardless of context.
- Output lists fixes grouped by class; REVIEW_REQUIRED items name the reviewer-relevant risk (e.g. "retry change affects load").
- Tests per §202 incl. boundary cases (timeout+cache combined fix → highest class wins).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- No fix generation or application — classification only.
- Default-deny: unclassified fix type → MANUAL_ONLY.
- Classification is deterministic from a table, not per-finding judgment.

# Review Notes

- Verify combined fixes escalate to the strictest class.
- Confirm justification text is generated from the rule, not free-form.
