---
id: 037-artifact-discovery
title: Artifact Discovery + EvidenceStore — single walk, classification, inventory
agent: claude
risk: medium
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §13, §14, §106
  ("are we duplicating filesystem traversal?").
- Problem: every analyzer calls `iter_files()` and re-probes every
  file; there is no shared inventory of what the project contains, so
  AnalysisPlan cannot exist and per-file work is duplicated.
- Out of scope: changing analyzer internals beyond accepting the
  discovered inventory; caching across runs (spec 065).
- Review failure: a registry that guesses artifact roles by substring
  matching (name-similarity smell); an EvidenceStore that mutates;
  traversal still duplicated per analyzer after the change.
- Riskiest assumption: classification can be exact — RESOLVED: classify
  by content markers where cheap (contract kinds, runtime adapter
  detect head) and by strong path/name signals otherwise; ambiguous →
  a documented `unknown`/multi-candidate class, never a guess.
- Smallest acceptable: `ArtifactDiscovery` producing a classified
  immutable inventory in ONE `iter_files` pass + `EvidenceStore`
  (lookup, dedup, sha256, origin) + tests; analyzers not yet rewired
  (spec 038-040 consume it).

# Context

§13: ProjectContext → Artifact Discovery → Artifact Classification →
Evidence Inventory. §14: EvidenceStore represents evidence, dedups
references, stores hashes, maps origin, feeds analyzers/handoff/context
broker; immutable in-memory structure. §106: avoid duplicated
filesystem traversal.

# Acceptance Criteria

- `core/discovery.py`: `ArtifactClass` enum (SOURCE, CONTRACT, RUNTIME,
  IAC, GATEWAY, MESH, POLICY, CONFIG, CLIENT, WORKSPACE, OWNERSHIP,
  DOCUMENTATION, UNKNOWN) — a file may carry multiple classes.
- `discover(context) -> ArtifactInventory`: exactly one filesystem
  walk; classification via strong markers only (existing adapter
  `detect` gates, contract format sniffers, manifest/policy filename
  rules documented in code); unclassified → UNKNOWN with reason, not
  dropped silently.
- `core/evidence_store.py`: frozen `EvidenceStore` — `register`
  returns a store; lookup by artifact path; `sha256` content hash per
  artifact (lazy or eager but deterministic); origin map (which
  analyzer classes claimed it); dedup identical content hashes with
  reference list.
- Sorted emission everywhere; no clock; tests incl. multi-class
  artifacts, empty project, adversarial names (random-yaml-named-openapi
  fixture class).
- pytest/ruff/mypy pass.

# Constraints

- No new deps; sha256 via stdlib hashl
