---
id: 068-docs-as-contract
title: Docs-as-contract — README/docs accuracy check + ADR set
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §98-§100.
- Problem: docs describe intent; after 035-067 they must describe
  reality. §98-100 ask for docs-as-contract (doc claims tested) and
  ADRs for the big decisions.
- Out of scope: rewriting docs that are already accurate;
  documentation of every module (ADRs cover decisions, not docs).
- Review failure: a doc-check test that parses prose (fragile);
  ADRs that are changelogs instead of decision records; docs left
  claiming pre-passo-1 behavior.
- Riskiest assumption: contract check form — RESOLVED: a structural
  test asserting (a) every CLI command in `typer` appears in
  docs/cli reference, (b) every output format documented exists in
  writers, (c) every docs/ link target exists, (d) README quickstart
  commands run — mechanical claims only, not prose.
- Smallest acceptable: doc-accuracy test + ADR-0001..0005 (unified
  engine, keep_spans default, mcp-optional-extra, untrusted-never-
  imported, refs-not-payloads) + docs refresh pass over the shipped
  deltas.

# Context

§98-§100: docs as contract + ADRs. Decisions record *why*; docs
describe *what is*.

# Acceptance Criteria

- `tests/test_docs_contract.py`: the four mechanical assertions
  above; docs drift fails tests.
- `docs/adr/`: ADR-0001 unified pipeline (inventory→plan→report),
  ADR-0002 keep_spans=False default + bounded retention, ADR-0003 mcp
  as optional extra, ADR-0004 untrusted plugins never imported,
  ADR-0005 compact refs over payloads in handoff/context — each with
  context/decision/consequences/alternatives.
- Docs refresh: architecture.md pipeline diagram updated,
  capabilities.md honest about shipped-vs-roadmap per spec 058+
  outcomes, README quickstart verified.
- pytest/ruff/mypy pass.

# Constraints

- ADRs are immutable once accepted; supersede, don't rewrite.
- Doc contract tests assert structure/mechanics, never prose.
