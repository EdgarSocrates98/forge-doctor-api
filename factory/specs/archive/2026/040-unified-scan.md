---
id: 040-unified-scan
title: Unified scan — scan_project consumes plan + all analyzers → DoctorReport
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §11, §15, §21.
- Problem: `forge-doctor-api scan` runs a subset (oas/security/
  reliability/clients-unknowns/runtime/graphql/grpc/asyncapi/policy/
  diff). Routes, gateway, iac, cache, twin, drift, fanout, capability —
  all real analyzers — never participate. Scan is not the Doctor.
- Out of scope: new checks families (each analyzer wires its existing
  checks/models); MCP/SDK surfaces (specs 044-045 consume the report).
- Review failure: findings emitted for domains with no evidence;
  behavior regressions in existing check outputs; filesystem walked
  per analyzer despite the inventory.
- Riskiest assumption: wiring order — RESOLVED: §15 pipeline order;
  models built lazily per plan; drift runs when routes exist; twin
  assembled after declared+observed models; gate semantics unchanged
  (UNKNOWN never blocks).
- Smallest acceptable: scan_project(context) → DoctorReport with all
  analyzers plan-driven + runtime loaded with keep_spans=False +
  identical-or-superset findings on lab fixtures + full green tests.

# Context

§11: `forge-doctor-api scan .` becomes the entry point for all
deterministic intelligence — no code duplication, unified pipeline.
§21: keep_spans default false.

# Acceptance Criteria

- `scan_project` rewritten: `discover → inventory → plan → analyzers
  (plan-gated) → models → graph merge → twin → checks → DoctorReport`.
- All existing check engines still run when their domain has evidence;
  new domains (routes drift, gateway, iac, cache, fanout, capability)
  contribute models/findings only where checks/models already exist —
  no fabricated findings.
- `keep_spans=False` in scan (and downstream call sites updated:
  mcp.py, lab/runner.py — runtime summaries still produced).
- CLI `scan` gains `--report` (full DoctorReport JSON) alongside
  existing formats; gate semantics unchanged.
- Lab suite still passes (no new FPs on adversarial corpus); pytest/
  ruff/mypy pass.

# Constraints

- One traversal (the inventory's); analyzers receive classified file
  lists, not the whole tree.
- No findings without evidence; absent domains are None in the report.
