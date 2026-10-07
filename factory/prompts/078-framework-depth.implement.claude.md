You are implementing Loop Factory spec `078-framework-depth`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\078-framework-depth.md`
        Spec hash: `992e073e804e864cbf573b3734d9721449347cef81d020f9e6fee4340460ac93`

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

- Owner: project owner; decisions from stabilization prompt Phase H.
- Problem: framework adapters exist (test_fastapi_routes,
  test_spring_adapter, test_js_adapters prove route extraction) but
  depth is uneven — error contracts, DI wiring, middleware chains,
  and framework-specific auth/validation idioms are under-evidenced.
- Out of scope: adding new frameworks beyond the four named;
  importing framework packages (detection is static/AST — never
  import target code, per boundary rules).
- Review failure: deeper detection implemented as regex guesses
  instead of AST evidence; capabilities asserted without evidence_refs;
  lab cases that pass because the fixture was written backwards from
  the analyzer.
- Riskiest assumption: four frameworks can share one depth model —
  RESOLVED: common capability surface (routes, auth deps, validation,
  error contract, middleware/filters, DI-provided clients) with
  per-framework evidence extractors; UNKNOWN where idiom is absent.
- Smallest acceptable: per-framework capability extraction for at
  least error-contract + auth-dependency + validation + client-
  injection evidence, each with lab scenario(s) covering a positive
  and an UNKNOWN case.

# Context

Phase H. Existing adapters: FastAPI (Python AST), Spring Boot (Java),
Express + NestJS (JS/TS). Existing lab scenarios cover basic route
detection. Deepening target: framework-aware evidence for auth
(dependency-injected guards/filters/middleware), validation
(Pydantic/Bean-Validation/class-validator/express-validator idioms),
error contract shape (HTTPException/ControllerAdvice/NestJS filters/
Express error middleware), outbound client injection
(Depends/@Autowired/constructor DI/providers).

# Acceptance Criteria

- Each of the four adapters extracts the four capability dimensions
  where idiom-static evidence exists; absent idiom → explicit
  `UnknownFact`, never silence.
- New lab scenarios `frameworks/{fastapi,spring,express,nestjs}-depth`
  with expected.yaml covering positive detection + expected unknowns.
- Adversarial: decorator-looking comments, commented-out code, and
  string-literal route strings must NOT produce findings.
- Capability records carry evidence_refs to file:line.
- `docs/frameworks.md` (new or extended) documents per-framework
  coverage matrix: supported idioms / detected / UNKNOWN.
- pytest/ruff/mypy pass; full lab corpus green.

# Constraints

- Pure static analysis — AST/regex-token evidence only, no imports,
  no execution of target code (boundary rules).
- All emitted collections sorted; ids follow `kind:domain:identifier`.
