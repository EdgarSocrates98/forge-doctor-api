---
id: 039-doctor-report
title: Unified DoctorReport — canonical compact report model
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §16 and §92.
- Problem: `ScanReport` carries findings+diff+gate+unknowns only; the
  normalized models (contracts, routes, gateway, iac, cache, runtime,
  security, reliability, capabilities, twin, graph) have no canonical
  single report — SDK/MCP/handoff/context all need one object.
- Out of scope: transport formats (output writers unchanged); bundling
  decisions (spec 047); heavy payloads — refs and summaries only.
- Review failure: a report that re-serializes entire source schemas;
  a report that drops unknowns; nondeterministic field ordering.
- Riskiest assumption: report shape — RESOLVED: metadata + inventory +
  per-domain compact projections (counts + entity ids + refs, not
  bodies) + findings + unknowns + graph + capabilities +
  knowledge_versions; domains absent → `None`, never fabricated.
- Smallest acceptable: `DoctorReport` model + `to_dict`/`to_json` +
  per-domain projections + tests; scan_project integration in spec 040.

# Context

§16 fields: metadata, project, artifacts, contracts, operations,
routes, clients, graph, gateway, mesh, infra, cache, runtime, security,
reliability, capabilities, policies, findings, unknowns, changes,
impact, migration, remediation_candidates, knowledge_versions. Compact
references, not heavy payloads.

# Acceptance Criteria

- `core/report.py`: `DoctorReport` frozen Model with the §16 field set,
  each domain as an optional compact sub-model (counts + ids +
  summaries; e.g. `ContractSummary{documents, operations}`, never raw
  schema bodies).
- `schema_version`, `tool_version`, `knowledge_versions`, artifact
  counts by class, analysis stats hook (spec 066 fills timing).
- `findings`, `unknowns`, `capabilities`, `remediation_candidates`,
  `changes`/`impact` when a baseline is provided.
- Deterministic serialization; unknowns preserved; tests for empty
  project, each domain presence/absence, redaction, byte-stable json.
- pytest/ruff/mypy pass.

# Constraints

- No payloads, no raw spans, no schema bodies — entity ids, counts,
  summaries, refs only.
