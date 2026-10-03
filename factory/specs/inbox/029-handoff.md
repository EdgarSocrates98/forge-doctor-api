---
id: 029-handoff
title: Handoff & integration — ApiHandoffBundle, MCP surface, Forger routing, decision intelligence
agent: claude
risk: medium
grill: required
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from §133–§138, §167, §215, §216.
- Problem: the Doctor's structured output must reach API Forge/The Forger without shipping whole repos (token economy §135).
- Out of scope: real MCP server transport wiring (interface + payload only — OPEN: confirm MCP endpoint surface ships as protocol definitions + local invocation, not a networked server in this pass), actual Forger implementation.
- Review failure: bundle contains raw repo content (§135 forbids), decision output presents subjective verdicts (§167 forbids), cross-domain graph merging (§138 forbids).
- Riskiest assumption: bundle field sufficiency for downstream consumers — mitigate by including unknowns explicitly per §134.
- Smallest acceptable: `ApiHandoffBundle` + `DecisionContext` answers + `ExternalReference` links + MCP method surface defined.

# Context

`ApiHandoffBundle` (§134): service, operations, relevant contracts, findings, breaking changes, clients affected, runtime regressions, security candidates, reliability signals, unknowns, remediation candidates. Token economy (§135): never send whole repos when the Doctor has structured the data. Forger integration (§136, §215): `domain=api` routes Doctor API → API Forge; API-dependency-pointing-to-data routes to Data Doctor. Cross-domain via `ExternalReference`/handoff links — no direct graph merging yet (§138). Decision intelligence (§167): facts, constraints, capabilities, tradeoffs, unknowns — never final subjective decisions.

# Acceptance Criteria

- `ApiHandoffBundle` (§134) assembled from existing outputs — compact, schema-versioned, secrets-redacted, includes explicit `unknowns` + remediation candidates (spec 022 classes).
- Decision-intelligence answers per §167 ("can v1 be retired", "can this move to gRPC", "can retry be enabled safely") returning facts/constraints/capabilities/tradeoffs/unknowns — no verdict.
- `ExternalReference` model (§138) for cross-domain links (e.g. API downstream → data-platform entity) — reference only, no merged graph.
- Forger routing contract (§136/§215): `domain=api` request/response shape documented + implemented as structured I/O.
- MCP method surface (§133) defined: get_service, get_api, get_operation, get_contract, get_clients, get_breaking_changes, get_blast_radius, get_runtime_baseline, get_regressions, get_security_findings, get_reliability_status, get_unknowns — as a typed local API surface behind `sdk.py`.
- Tests per §202 incl. bundle redaction and unknowns presence; `python -m pytest -q`, `ruff`, `mypy` pass.

# Constraints

- Bundles are compact by design (§135) — references + summaries, not payloads of source.
- No verdicts in decision output (§167); the Doctor informs, never decides product direction.
- No graph merging across domains (§138).

# Review Notes

- Verify bundle size discipline — handoff of a large service stays bounded.
- Confirm MCP surface is callable without a server (local invocation) and payloads are serializable for future transport.
