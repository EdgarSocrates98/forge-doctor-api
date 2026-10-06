---
id: 052-express-nest-adapter
title: Express + NestJS adapter — static JS/TS route discovery
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §42, §45, §46.
- Problem: second gen-one adapter family — JS/TS (Express, NestJS) —
  same no-exec, evidence-first rules as Spring.
- Out of scope: full TypeScript parsing (decorator/method-call level
  extraction only); runtime resolution of `app.use(router)` wiring
  beyond direct static evidence.
- Review failure: template-string paths treated as static;
  `router.METHOD(dynamic)` resolved without evidence; NestJS
  `@Controller()` decorators missed because scanning is
  call-expression-only.
- Riskiest assumption: JS/TS scan precision — RESOLVED: two-mode
  scanner — NestJS mode (decorator/state-machine like Spring:
  @Controller/@Get/@Post/...@UseGuards) and Express mode
  (comment/string-stripped regex over
  `app|router\.(get|post|put|delete|patch|use)\(` with literal-string
  path args); non-literal/dynamic → CANDIDATE/UNKNOWN.
- Smallest acceptable: adapter covering both styles via the spec-050
  contract, adversarial fixtures (template strings, aliased imports,
  nested routers, conditional registration, vendored node_modules),
  conformance suite green.

# Context

§45, §46 adversarial list applies fully; §48-49 same as spec 051.

# Acceptance Criteria

- `analyzers/routes/javascript.py`: `ExpressAdapter` + `NestJsAdapter`
  (or one `JavaScriptAdapter` with mode detection) implementing the
  spec-050 contract.
- Detect: package.json deps (@nestjs/*, express), file markers,
  decorator imports.
- NestJS: `@Controller('prefix')` + method decorators → routes;
  `@UseGuards`/metadata → auth candidates; DTO decorators → schema
  candidates.
- Express: literal-path `app|router.METHOD()` + `use(prefix,router)`
  prefix composition where statically literal; middleware chains
  recorded as middleware candidates.
- Adversarial fixtures: template-literal paths → UNKNOWN not literal;
  commented code, strings containing `app.get`, node_modules/vendor
  excluded, dynamic registration → CANDIDATE.
- Lab fixtures + spec-050 conformance suite green; no new FPs.
- pytest/ruff/mypy pass.

# Constraints

- Stdlib-only scanning; strip comments and string contents before
  structural matching.
