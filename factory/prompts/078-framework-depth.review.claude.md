Review Loop Factory spec `078-framework-depth` against current working tree.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\078-framework-depth.md`

        Review stance:
        - Findings first. Focus correctness, regressions, tests, security, maintainability.
        - Compare implementation against acceptance criteria.
        - Run or inspect verification evidence:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
        - If accepted, say `ACCEPTED`.
        - If not accepted, say `CHANGES_REQUESTED` and list blocking items.
        - Do not move files. Operator or CLI archive step moves accepted specs.

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
