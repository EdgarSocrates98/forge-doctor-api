You are implementing Loop Factory spec `076-runtime-scale-proof`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\076-runtime-scale-proof.md`
        Spec hash: `d5e416410fbee7018bf9526596d503564d2b64803b7240b6e17b52c285b92adf`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Claude Code subagents or dynamic workflows only when task is parallel. Prefer project skills in .claude/skills when relevant.

        Required verification:
        - `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy src`
- `python factory/benchmarks/scale_benchmark.py --check`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions from stabilization prompt Phase F + J.
- Problem: runtime evidence exists (test_runtime_*, test_temporal,
  factory/benchmarks/scale_benchmark.py) but there is no enforced
  budget — regressions land silently.
- Out of scope: real-time tail capture redesign; wall-clock use inside
  the engine (inject via ProjectContext always).
- Review failure: perf thresholds so loose they never fire, or so
  tight they flake on CI hardware; memory curve tests that depend on
  GC timing.
- Riskiest assumption: benchmark thresholds will flake on GitHub
  runners — RESOLVED: budgets expressed as multiplicative headroom
  over a baseline recorded on CI hardware; check mode tolerates
  `baseline * HEADROOM`, baseline committed under
  `factory/runs/scale-benchmark.json` and refreshed only via a
  deliberate regeneration commit.
- Smallest acceptable: streaming caps proven (row counts bounded by
  config not corpus size), RSS growth sub-linear vs input growth,
  tombstone round-trip semantics in snapshots, snapshot migration
  forward-compat test, benchmark `--check` gate wired into CI.

# Context

Phases F+J. `factory/benchmarks/scale_benchmark.py` already synthesizes
N-endpoint corpora and writes `factory/runs/scale-benchmark.json`.
Existing coverage: `test_runtime_stream.py`, `test_runtime_evidence.py`,
`test_runtime_aggregate.py`, `test_temporal.py`, `test_incremental.py`,
`test_performance.py`. Gaps: no enforced budget gate; no memory curve;
tombstone/snapshot-migration semantics unasserted.

# Acceptance Criteria

- `scale_benchmark.py` gains `--check`: loads committed baseline,
  fails if any metric exceeds `baseline * HEADROOM` (per-metric
  headroom table in the file header); `--write-baseline` regenerates.
- New `test_scale_proof.py`: (a) synthesized 1k/4k/8k-endpoint corpus
  memory growth is sub-quadratic (RSS delta ratio bound), (b) runtime
  stream emits at most `limit` rows regardless of corpus size,
  (c) tombstoned operations survive snapshot round-trip and are
  excluded from current-state entities but retained in history,
  (d) snapshot written by format N-1 loads under N (migration shim or
  explicit versioned reject with reason).
- `test_performance.py` budgets asserted in `--check` terms rather
  than absolute wall-clock where they currently are absolute — keep
  existing absolute guards only where they are coarse (≥5x slack).
- Quality workflow runs `scale_benchmark.py --check` in the full job.
- Docs: `docs/runtime-scale.md` (or architecture.md section) records
  the budget model, baseline refresh policy, and memory-curve method.
- pytest/ruff/mypy pass; `--check` green on committed baseline.

# Constraints

- RSS measurement via `resource`/`psutil`-free stdlib only
  (`tracemalloc` or `resource.getrusage` where available; skip-with-
  reason on platforms without it — Windows CI uses tracemalloc).
- No wall-clock reads in engine code; benchmark harness may time, but
  thresholds must not assert wall-clock on shared CI.
