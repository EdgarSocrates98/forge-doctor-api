---
id: 025-fleet
title: Fleet intelligence — portfolio, complexity, deprecation readiness, external APIs
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
  - python -m forge_doctor_api inventory --help
---

# Grill Gate

- Owner: project owner; decisions sourced from §110, §111, §112, §114, §115, §159, §190, §191.
- Problem: answer fleet-level questions (who exposes what, what's unowned, what's repeatedly regressing) across a workspace.
- Out of scope: migration execution (028), org dashboards/UI — output is data + CLI.
- Review failure: complexity signals reported as errors (§112 says opportunity), a single "health score" (§191 forbids), external hosts leaked unsanitized (§115).
- Riskiest assumption: aggregation semantics across partial workspaces — RESOLVED: UNKNOWN propagates upward; unscanned/partial repos are represented as UNKNOWN entries, never silently excluded.
- Smallest acceptable: §110 question set + portfolio + complexity signals + `DeprecationReadiness` + `ExternalAPI` model + inventory CLI + §191-style count output.

# Context

Fleet questions (§110): which services expose public APIs; which APIs have no owners; which operations lack auth evidence; which services use deprecated versions; which endpoints repeatedly regress; which share external dependencies. Portfolio (§111): REST/GraphQL/gRPC/Async/Gateways/ExternalAPIs. Complexity signals (§112): same capability over 4 protocols, same external dep wrapped by 10 services, 3 gateways in a path, multiple auth models — *opportunity, not error*. `DeprecationReadiness` (§114): remaining_clients, observed_traffic, replacement, contract_age, unknowns. `ExternalAPI` (§115): host, operations, timeout, retry, auth, owner, criticality — host sanitized if needed. Quality dimensions (§190) without magic score; health output as counts (§191). `inventory` CLI (§159).

# Acceptance Criteria

- Fleet queries answering §110's six questions over a workspace scan; each result carries evidence + unknowns.
- `PlatformPortfolio` (§111): counts/inventory per API style + gateways + external APIs.
- `ComplexitySignal` (§112): the four listed patterns detected and reported as *opportunities* with evidence, not findings of error.
- `DeprecationReadiness` (§114) per deprecated API: remaining clients (from spec 009/024), observed traffic (from runtime evidence), replacement, contract age; missing inputs → UNKNOWN fields.
- `ExternalAPI` model (§115) with host sanitization option; unsafe-dependency signals stay candidate-level.
- `ApiQualityModel` dimensions (§190) reported per-dimension with evidence — no composite score.
- Health output per §191 format: counts of breaking changes / reliability gaps / security candidates / runtime regressions / unknowns.
- `forge-doctor-api inventory` CLI (§159): services, APIs, operations, protocols, public/internal, versions, owners — console + JSON.
- Tests per §202 incl. empty/partial workspaces; `python -m pytest -q`, `ruff`, `mypy` pass.

# Constraints

- Complexity = opportunity signal, never error severity (§112).
- No single health number (§191).
- External host data sanitized per policy (§115).
- Aggregation honestly propagates UNKNOWN (don't silently exclude unscanned repos).

# Review Notes

- Verify deprecation readiness distinguishes "no clients found" from "no client evidence available" (UNKNOWN).
- Confirm inventory never fabricates owners — missing owner is itself a fleet answer.
