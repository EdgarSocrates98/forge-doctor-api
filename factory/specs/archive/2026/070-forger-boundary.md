---
id: 070-forger-boundary
title: Cross-doctor + The-Forger boundary — contract surface documentation
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §108-§110, §115.
- Problem: after 046-049 ship the Doctor-side protocol, the product
  boundary needs one authoritative contract doc + typed boundary
  module so future work cannot blur Doctor into orchestration or
  coding-agent territory.
- Out of scope: implementing The Forger or API Forge (other repos);
  any runtime coupling — this is a contract + docs surface.
- Review failure: boundary doc that promises behaviors not in code;
  a "convenience" API that lets callers route work to API Forge
  (violates boundary); cross-doctor intelligence implemented as
  remote calls.
- Riskiest assumption: cross-doctor scope — RESOLVED: cross-doctor
  intelligence = typed import of *other* DoctorReports/Handoffs
  (fleet aggregation already exists; extend fleet to accept Forge
  Handoffs as inputs) — never network federation.
- Smallest acceptable: `handoff/boundary.py` (typed boundary surface:
  what Doctor accepts/emits, nothing else) + fleet accepting
  ForgeHandoff inputs + docs/forger-boundary.md as the authoritative
  product-boundary contract.

# Context

§108-§110: cross-doctor intelligence, The-Forger contract boundary.
§115 explicit non-goals. The boundary is enforced by types, not
convention.

# Acceptance Criteria

- `handoff/boundary.py`: `DoctorBoundary` — typed in/out surface:
  accepts ForgeRequest, emits ForgeHandoff/ForgeResult; contains no
  methods that route, schedule, implement, or call out (import-time
  assertion test: module has no network/subprocess deps).
- `fleet/` accepts `ForgeHandoff` as an aggregation input (report-
  equivalent compact fields only).
- `docs/forger-boundary.md`: authoritative boundary contract — what
  Doctor owns (observe/normalize/detect/measure/diagnose/classify/
  impact/unknowns/context), what it never does (the §115 list), the
  typed integration points (ForgeRequest→ForgeHandoff→ForgeReceipt).
- Tests: boundary module purity (AST scan: no
  socket/subprocess/import-target-code), handoff-into-fleet round
  trip, docs link contract.
- pytest/ruff/mypy pass.

# Constraints

- Boundary enforced by the module's exports + AST test — never
  convention alone.
