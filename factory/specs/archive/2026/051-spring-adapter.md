---
id: 051-spring-adapter
title: Spring Boot adapter — static route/auth/schema discovery (Java/Kotlin)
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §42, §44, §46.
- Problem: Doctor understands FastAPI only at source level; §42-§46
  require Spring Boot as framework generation one, no target-code
  execution, adversarial-hardened.
- Out of scope: Kotlin-specific AST beyond annotation extraction
  (Kotlin files handled at annotation/regex level — full kotlin
  parsing is roadmap); DI graph completeness (annotations only).
- Review failure: matching commented-out/string annotations as routes;
  "executing" anything; name-similarity edges; FP on vendored/
  generated sources.
- Riskiest assumption: Java parsing without a dependency — RESOLVED:
  zero-dep source scanner (strip comments + string literals, then
  annotation-state machine over `@RequestMapping`/`@GetMapping`/
  `@PostMapping`/.../`@RestController`/`@Controller`,
  `@PathVariable`/`@RequestParam`/`@RequestBody`, `SecurityConfig`/
  `@PreAuthorize`, `application.{yml,properties}`); ambiguity →
  `Confidence.CANDIDATE` + UnknownFact.
- Smallest acceptable: adapter satisfying the spec-050 contract for
  routes+auth+schemas+deps, comment/string-safe, golden+adversarial
  fixtures, parity conformance suite green.

# Context

§42-§44: Spring Boot, Express/Nest as gen one; §46 adversarial
fixtures (comments with fake routes, strings containing decorators,
generated/vendored/dead source, dynamic routes, aliased imports,
nested routers, conditional registration). §48-49: no execution, no
name-inference.

# Acceptance Criteria

- `analyzers/routes/spring.py`: `SpringBootAdapter` implementing the
  spec-050 contract; `detect()` on pom.xml/build.gradle +
  `org.springframework` imports/annotations.
- Route discovery: controller classes + method mapping annotations →
  RouteModel entries (method, path-template, controller file:line
  evidence); nested/class-level prefixes composed; `value`/path
  attribute variants handled.
- Auth: `@PreAuthorize`, SecurityFilterChain beans, permitAll —
  extracted as capability candidates with evidence.
- Schemas: `@RequestBody`/DTO class names → schema candidate refs
  (name + location only — fields are roadmap).
- Adversarial: commented annotations, annotation-in-string,
  generated-sources/ and vendored dirs excluded or marked, conditional
  `@ConditionalOnProperty` registration → CANDIDATE not PASS.
- Lab fixtures under labs/{golden,adversarial}/spring-*; conformance
  suite from spec 050 passes; no new FPs on existing corpus.
- pytest/ruff/mypy pass.

# Constraints

- No execution, no Java tooling, no new deps — scanner is stdlib text
  processing with comment/string stripping.
- UNKNOWN wherever evidence is ambiguous; never guess.
