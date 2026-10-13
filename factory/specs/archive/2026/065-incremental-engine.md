---
id: 065-incremental-engine
title: Doctor performance — incremental analysis groundwork + engine benchmarks
agent: claude
risk: high
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
---

# Grill Gate

- Owner: project owner; decisions sourced from prompt §88-§90.
- Problem: every scan is full-scan; on large repos unchanged
  artifacts get re-analyzed every run. §88-90 ask for incremental
  analysis keyed on artifact hashes + an engine benchmark.
- Out of scope: cross-process cache persistence guarantees (cache is
  a best-effort accelerator under `.forge-doctor/cache/`);
  parallelizing analyzers (roadmap).
- Review failure: stale results served after an artifact changed
  (cache key weaker than content); cache silently poisoning
  determinism; benchmarks claiming speedups without cold/warm
  separation.
- Riskiest assumption: cache key — RESOLVED: sha256 artifact content
  (from EvidenceStore) + analyzer id + tool_version + config digest;
  invalid on any change; cache stores analyzer-level compact model
  json only — never findings (findings re-derive each run to keep
  cross-artifact checks correct).
- Smallest acceptable: `AnalysisCache` (file-backed, opt-in
  `--incremental`), per-artifact model memoization for the heavy
  analyzers, invalidation tests, engine benchmark (wall/mem per
  analyzer on lab corpus, cold vs warm).

# Context

§88-§90: engine performance + incremental analysis. Cache is an
accelerator — correctness must be identical with/without.

# Acceptance Criteria

- `core/cache.py`: `AnalysisCache` — get/set analyzer-level model
  payloads keyed (artifact_sha256, analyzer_id, tool_version,
  config_digest); file-backed under `.forge-doctor/cache/`, created
  only with `--incremental`; misses/failures degrade to full
  analysis, never error.
- Wired into scan for the heaviest analyzers (openapi contract,
  runtime aggregation, iac); findings/checks always recompute.
- Equivalence test: identical report bytes with cache cold vs warm;
  touching one artifact invalidates only its analyzer keys.
- `factory/benchmarks/engine_benchmark.py`: per-analyzer wall/mem on
  the lab corpus + repo self-scan, cold/warm comparison, record to
  factory/runs/.
- pytest/ruff/mypy pass.

# Constraints

- Cache never stores findings, unknowns, or cross-artifact results.
- Opt-in only; default path unchanged.
