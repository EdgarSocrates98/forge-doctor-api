You are implementing Loop Factory spec `086-runtime-scale-expansion`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\086-runtime-scale-expansion.md`
        Spec hash: `3447df4247b8db2d380ea83dca96d67a6c9a8cf6d9a1735159bedf918545d3d9`

        Operating rules:
        - Treat spec as source of truth.
        - Automate code generation and verification, not product decisions.
        - If spec is ambiguous, make smallest reversible assumption and record it in implementation notes.
        - Keep changes scoped to acceptance criteria.
        - Update living spec only for facts learned from implementation or tests.
        - Do not archive spec. Review step does that.
        - Use Codex subagents when work splits cleanly. Ask explicitly before spawning. Keep final answer terse with files changed and checks run.

        Required verification:
        - `python -m pytest -q`
- `python factory/benchmarks/scale_benchmark.py --check`
- `python -m ruff check .`

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions from `prompt_evo_rc_hardening.md`
  Phase 6 and items §11/§14.
- Problem: the scale gate exists (1k endpoints / 10k spans in CI,
  baseline to 1M spans locally) but the recorded envelope is narrow
  in *what it measures*: wall time + peak memory only. RC needs
  executions/traces/evictions/tombstones/snapshot-size measured at
  the promised envelope, plus documented behavior past the bound.
- Out of scope: vanity scale beyond the 10k/100k envelope (prompt:
  "do not chase vanity scale"); distributed ingestion; persistence
  formats.
- Review failure: a benchmark that reports times but not whether
  ingestion stayed correct under pressure; snapshot size claims
  without a measured curve; headroom multipliers tuned to pass.
- Riskiest assumption: the streaming assembler stays correct at
  100k spans with eviction/tombstones — RESOLVED by asserting on
  trace counts and invariants in the benchmark itself, not just
  timing.
- Smallest acceptable: benchmark records the full metric set;
  envelope documented at 5k/50k (check-tier) and 10k/100k
  (recorded-tier); snapshot write/load/diff sizes recorded; edge-
  case tests for the assembler; runtime-docs updated.

# Context

Phase 6. Existing: `analyzers/runtime/stream.py` (bounded, eviction,
tombstones), `temporal/` windows, `factory/benchmarks/
scale_benchmark.py` + baseline JSON + `--check` in CI (4x time /
2.5x memory headroom). Missing: full metric set in the artifact,
snapshot-size curve, assembler edge-case coverage, documented
envelope table.

# Acceptance Criteria

- `scale_benchmark.py` records per scale: wall_seconds,
  peak_bytes, executions generated, traces completed, traces
  incomplete, evictions, tombstones, and — for the snapshot suite —
  snapshot file bytes, load time, diff time. Baseline JSON holds
  the full metric set.
- Measured envelope: check-tier asserts 5,000 endpoints / 50,000
  spans within headroom; recorded-tier (default run) covers
  10,000 endpoints / 100,000 spans. If a larger tier is
  unreasonable on CI it is marked `measured: false` in the docs,
  not silently skipped.
- Correctness assertions inside the benchmark: at each scale the
  assembled trace inventory equals the generated ground truth
  (completed+incomplete counts match); evictions/tombstones only
  occur when the bound is exceeded — measured, not assumed.
- Assembler edge-case tests (`tests/test_runtime_stream.py` or
  new): late spans after close, duplicate span ids, out-of-order
  arrival, missing parent, eviction under bound, tombstone
  accounting — each with observable expected output.
- Snapshot suite: write/load/diff at the recorded scale records
  byte size + time into the baseline; a test asserts snapshot round
  trip preserves the bounded runtime summary.
- `docs/runtime-scale.md` (new or extend): measured envelope table
  (scale, wall, peak, per-scale metric columns), degradation
  behavior past the bound (tombstones recorded as unknowns),
  reproduction commands.
- `docs/release-evidence.md` gains the new benchmark numbers.
- pytest/ruff pass; benchmark `--check` passes with the expanded
  metric set.

# Constraints

- Benchmark stays stdlib-only + tracemalloc; no new deps.
- CI `--check` runtime must not regress meaningfully — keep check
  tiers proportional (5k/50k) and record-only tiers out of CI.
- No vanity scale: if 10k/100k is uncomfortable on the dev box,
  document the measured envelope and stop.
