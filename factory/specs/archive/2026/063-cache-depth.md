---
id: 063-cache-depth
title: Cache intelligence depth — invalidation graph + coherence candidates
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §82-§84.
- Problem: CacheModel (spec 034) stores policies + risk candidates
  per entity; §82-84 want the *graph* — which writes invalidate
  which cached reads, coherence windows, cross-layer candidates.
- Out of scope: cache performance simulation; TTL recommendation
  (recommendations stay roadmap).
- Review failure: invalidation edges drawn between operations sharing
  only a path prefix; coherence findings when no cross-layer evidence
  exists; verdict language on candidates.
- Riskiest assumption: invalidation edge basis — RESOLVED: write→read
  edge requires shared entity evidence (same schema ref in a mutation
  request AND a cached response, or declared invalidation hook);
  path-prefix alone → no edge.
- Smallest acceptable: `CacheCoherenceGraph` (cached-read nodes,
  mutation nodes, evidence edges) + stale-window candidates +
  cross-layer policy conflict candidates + tests.

# Context

§82-§84: invalidation graph + coherence. Builds on ApiCacheModel +
  graph slices. Candidates, never verdicts.

# Acceptance Criteria

- `cache/graph.py` (or analyzers/cache/graph.py): graph over
  ApiCacheModel — cached operations, mutating operations, edges where
  schema-level evidence links mutation→cached-read.
- Stale-window candidates: declared ttl present + evidenced writer →
  CANDIDATE finding with the window math from literals.
- Cross-layer conflict candidates: two layers declare policies on the
  same operation with conflicting stale_policy → CANDIDATE.
- Every edge/finding lists its evidence; name-only → nothing.
- Tests: schema-linked edge, prefix-only no-edge, stale-window math,
  layer conflict, determinism.
- pytest/ruff/mypy pass.

# Constraints

- Declared-or-unknown; candidate-grade output only.
