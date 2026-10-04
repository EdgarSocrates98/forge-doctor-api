---
id: 057-graph-slices
title: Graph 2.0 — slice projections + evidence-backed edge export
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §67-§69.
- Problem: `core/graph.py` builds the entity/relationship DAG but
  consumers get the whole graph or nothing; there is no
  per-service/per-operation slice or edge-export carrying evidence.
- Out of scope: layout/visualization; graph diff (spec 049 covers
  delta at report level).
- Review failure: slices that drop edges silently (an edge's evidence
  surviving but the edge not in the slice); export losing the
  evidence ids making edges unfalsifiable.
- Riskiest assumption: slice semantics — RESOLVED: slice(root_id,
  depth, direction) = BFS bounded subgraph + every edge carrying its
  Relationship.evidence refs; nodes outside the cut listed as
  `boundary` ids only — no phantom nodes.
- Smallest acceptable: `graph_slice(graph, ref, depth, direction)` +
  `export_edges(graph)` evidence-carrying list + tests + context
  broker integration (doctor://graph/{service} serves slices).

# Context

§67-§69: graph slices for service/operation blast-radius views;
evidence-backed relationship export for handoff. Edges are already
evidence-required — slicing must preserve that.

# Acceptance Criteria

- `core/graph.py` additions: `slice_graph(graph, root_id, *,
  depth=1, direction="both") -> GraphSlice{nodes, edges, boundary_ids}`
  — every edge keeps evidence refs; boundary nodes appear as ids only.
- `export_edges(graph) -> tuple[EdgeExport]` where EdgeExport carries
  (from_id, to_id, kind, evidence_ids, confidence).
- Context broker (spec 048) `doctor://graph/{service}` serves
  `slice_graph` output; handoff V2 (spec 047) can embed slices.
- Tests: bounded depth, direction filter, boundary marking, evidence
  preservation, determinism, empty/disconnected roots → empty slice +
  unknown.
- pytest/ruff/mypy pass.

# Constraints

- Slices never fabricate nodes/edges to "complete" a picture.
