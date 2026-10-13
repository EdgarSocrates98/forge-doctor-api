---
id: 050-adapter-contract
title: FrameworkAdapter contract consolidation — shared discovery surface
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §38-§41.
- Problem: `plugins/sdk.py` declares a `FrameworkAdapter` Protocol
  (detect/discover_routes) but it is a protocol-in-name-only for
  FastAPI internals; the real FastAPI logic lives in
  `analyzers/routes/fastapi.py` outside the contract, so adapters for
  other frameworks have no shared discovery surface to implement.
- Out of scope: new framework adapters (specs 051-052 use this
  contract); executing target code — static AST/manifest only.
- Review failure: contract methods so FastAPI-shaped that a Java/JS
  adapter must fake return types; the FastAPI adapter diverging from
  existing detection results (regression).
- Riskiest assumption: surface scope — RESOLVED: the §39 list
  verbatim (attribute, discover_routes, discover_auth,
  discover_schemas, discover_dependencies, discover_middleware,
  discover_error_handlers, discover_validation,
  discover_serialization, discover_client_calls), each returning
  Optionals/empties when the framework cannot answer — UNKNOWN, not
  fabricated.
- Smallest acceptable: contract module in `analyzers/routes/` +
  FastAPI adapter refactored to implement it (parity tests) +
  contract conformance test an adapter must pass.

# Context

§38: adapters extract capabilities from framework conventions,
config, decorators, annotations, manifests — never execute target
code. §39: adapter surface. §41: contract-based intelligence, no
fragile heuristics as facts.

# Acceptance Criteria

- `analyzers/routes/adapter.py`: `FrameworkAdapter` Protocol with the
  §39 method set; return types reusing existing route models +
  `UnknownFact`s where the framework cannot answer.
- `analyzers/routes/fastapi.py` refactored to satisfy the protocol —
  same discover_routes output on all existing fixtures (byte-parity
  test), additional surface implemented where static AST evidence
  supports it (auth deps, middleware list, error handlers) else None.
- `FrameworkConformance` test helper: runs a shared
  protocol-conformance suite against any adapter (determinism,
  no-exec, unknown-on-absence, sorted output).
- Registration: `available_adapters()` returns adapters whose
  `detect()` matches the project; unknown frameworks → unknown fact,
  never an adapter guess.
- Existing route tests all pass unchanged; new conformance tests for
  FastAPI; pytest/ruff/mypy pass.

# Constraints

- AST only; never import target modules.
- A method returning None/empty must also produce an UnknownFact.
