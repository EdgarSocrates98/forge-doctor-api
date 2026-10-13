---
id: 048-context-refs
title: Context Broker — doctor:// refs and compact context slices
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §34-§36.
- Problem: consumers ask for "the service", "the operation", "the
  finding" and get whole documents or nothing. There is no stable
  reference scheme or bounded slice extraction.
- Out of scope: MCP resource serving (spec 045 reuses these refs);
  delta computation (spec 049); token estimation precision beyond a
  documented heuristic.
- Review failure: refs that embed file paths instead of stable ids;
  slices leaking payloads; a token "savings" number with no
  measurement backing.
- Riskiest assumption: ref grammar — RESOLVED: §35 list verbatim
  (`doctor://service/{id}`, `doctor://operation/{id}`,
  `doctor://finding/{rule}/{digest}`, `doctor://runtime/{service}`,
  `doctor://graph/{service}`, `doctor://contract/{service}`,
  `doctor://unknown/{service}/{topic}`, `doctor://handoff/{id}`) —
  parsed into (kind, parts) tuples.
- Smallest acceptable: `context.py` (broker) with ref mint + parse +
  `slice(report, ref)` for service/operation/finding/runtime/graph/
  contract/unknown/handoff + size metrics + tests.

# Context

§34: Context Broker; §35 ref list; §36: measure raw-project context
vs bundle bytes, estimated token reduction, evidence retained,
unknowns preserved.

# Acceptance Criteria

- `handoff/context.py` (broker): `mint(kind, **parts) -> str`,
  `parse(uri) -> ContextRef`, strict validation, unknown kinds → error.
- `context_slice(report, ref) -> ContextSlice` for all §35 kinds:
  frozen model with the minimal fields for that kind (service →
  entity + ops summary + findings ids; finding → finding + evidence;
  graph → adjacency slice bounded; unknown → the UnknownFact).
- Size metrics: `measure(report) -> ContextMetrics` {raw_bytes
  (canonical full report json), slice_bytes, estimated_tokens
  (chars//4 documented heuristic), evidence_refs, unknowns}.
- Refs are stable: same report → same ref ids (digest-based where a
  digest is part of the grammar).
- Tests: parse/mint round trip, each slice kind, bounded output
  (slice never exceeds a documented cap), determinism, metrics on a
  lab fixture.
- pytest/ruff/mypy pass.

# Constraints

- Slices are views — no mutation, no new analysis.
- Never emit raw source/schema/span bytes in a slice.
