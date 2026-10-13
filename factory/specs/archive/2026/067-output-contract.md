---
id: 067-output-contract
title: Output contract hardening — versioned schemas, SARIF/agent polish
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §94-§96.
- Problem: outputs carry schema_version but there is no versioned
  contract doc, no backward-compat test, SARIF/agent formats are
  "works today" not contracted.
- Out of scope: new formats; changing the v1 schemas (contract
  freezes them; changes → v2).
- Review failure: contract tests pinned to implementation details
  instead of the documented schema; SARIF output failing the official
  schema validator shape; agent format emitting non-compact payloads.
- Riskiest assumption: contract surface — RESOLVED: document each
  output format's v1 schema (fields, optionality, ordering) in
  docs/output-contract.md; golden-shape tests (presence/absence/type
  of fields) per format; SARIF validated against the 2.1.0 schema
  json committed in-repo.
- Smallest acceptable: docs/output-contract.md + per-format contract
  tests + SARIF schema-validation test + version-bump rules in docs.

# Context

§94-§96: output contract, SARIF, agent format. §33: version
schema/output/handoff/mcp — this spec freezes output v1.

# Acceptance Criteria

- `docs/output-contract.md`: per-format v1 schema tables (field,
  type, optional, semantics) for json, jsonl, sarif, agent, report;
  version-evolution rules (additive → minor, removal → major).
- `tests/test_output_contract.py`: structural contract tests per
  format (assert documented fields exist with correct types;
  undocumented required-fields absent); SARIF output validates
  against committed sarif-2.1.0-schema.json via a minimal stdlib
  validator (required/type checks on the rules subset we emit).
- Agent format bounded-size test (fits documented cap on lab corpus).
- pytest/ruff/mypy pass.

# Constraints

- Contract describes v1 as-is; no schema changes in this spec.
