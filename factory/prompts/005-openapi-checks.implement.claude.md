You are implementing Loop Factory spec `005-openapi-checks`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\005-openapi-checks.md`
        Spec hash: `0198193a99cf7d8f484bda8b01df92840ca138d96c961a9e3a761d9b5c41cdb6`

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

- Owner: project owner; decisions sourced from §11, §50 (analogous caution), §101, §199–§202.
- Problem: turn the OpenAPI model into actionable, low-false-positive findings (§225 Phase E).
- Out of scope: drift (007), compatibility (008), security engine (018) — OAS010/011 stay contract-evidence-level only.
- Review failure: high false positives, finding without evidence_kind, check firing on weak markers, unstable check IDs.
- Riskiest assumption: which checks can fire without organization context — mitigate by emitting `candidate`/unknown-confidence where §11 implies judgment (OAS010/017/020).
- Smallest acceptable: OAS001–OAS020 implemented, each with positive+negative+adversarial tests and declared evidence kind.

# Context

Phase E (§225). Check namespace `OAS###` (§11, §218 — never renumber stable IDs). Low false positive is the top priority (§11, §101): every check declares its evidence kind, and checks that need org context (security posture, ownership, environment) emit candidates with explicit confidence/unknowns rather than assertions.

# Acceptance Criteria

- Checks implemented per §11: OAS001 invalid spec version; OAS002 unresolved local ref; OAS003 duplicate operationId; OAS004 operation without operationId; OAS005 undocumented response; OAS006 default-only response; OAS007 inconsistent error schema; OAS008 request body missing schema; OAS009 response missing schema; OAS010 public API without security requirement; OAS011 operation overrides security unexpectedly; OAS012 path parameter mismatch; OAS013 required path param not declared; OAS014 schema without type info; OAS015 deprecated API without sunset metadata; OAS016 server URL environment mismatch; OAS017 unrestricted additionalProperties candidate; OAS018 unused component schema; OAS019 circular ref depth risk; OAS020 operation without tags/domain ownership.
- Each check: stable id, severity, confidence, evidence_kind, entities, source_location, and documented trigger conditions.
- Judgment-dependent checks (OAS010, OAS016, OAS017, OAS020) emit candidate-level findings with explicit unknowns — never assert violations without evidence (§101 philosophy).
- Findings serialize through spec 002's contract with `schema_version`.
- Test contract per §202 for every check: positive, negative, malformed, adversarial, determinism. Include §100 adversarial inputs — no check may fire on non-OpenAPI input.
- A precision harness records per-check expected/forbidden findings on fixtures (aligns with §199–§201; full lab lands in spec 026).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Check IDs are stable and never renumbered (§218).
- No network, no live spec lookups — behavior from parsed model + bundled knowledge only (§129).
- Do not report "vulnerability confirmed" style language; OAS010 is a security-requirement evidence finding, not a vuln verdict (§50 spirit).

# Review Notes

- OAS005/006/007 interact (default-only vs undocumented) — check for double-reporting.
- OAS003 across multi-file documents: duplicate operationId detection must span merged docs.
- Confirm OAS012/013 handle `{param}` templates vs declared parameters both directions.
