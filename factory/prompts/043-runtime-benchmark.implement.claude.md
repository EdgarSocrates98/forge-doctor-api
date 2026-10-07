You are implementing Loop Factory spec `043-runtime-benchmark`.

        Native adapter: `claude`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\043-runtime-benchmark.md`
        Spec hash: `8eda37be0624c7ac3c0fb93c108e6264dfe9ff81410e7755ce2c3ef8f48e6112`

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

        Deliverables:
        1. Implement acceptance criteria.
        2. Run verification commands or explain why unavailable.
        3. Add notes under `factory/runs/` or in final response: changed files, checks, open risks.
        4. Leave spec in `factory/specs/active/` for review.

        Spec:
        ---
        # Grill Gate

- Owner: project owner; decisions sourced from prompt §22, §23, §103.
- Problem: scale record exists once (`scale-benchmark.json`, manual);
  no suite measuring wall/cpu/peak-memory/records-sec/trace-completion/
  unknown-rate across sizes, no machine-independent regression gate.
- Out of scope: engine-level repo benchmarks (spec 065); CI perf
  enforcement (quality.yml runs it as an informational job — flaky
  cross-machine thresholds make hard CI gates wrong).
- Review failure: a benchmark that lies (warm-cache numbers presented
  as cold); thresholds so tight they fail on different hardware;
  missing environment record making results non-reproducible.
- Riskiest assumption: regression measure — RESOLVED: records/sec +
  peak-memory-per-record ratios vs the previous recorded run, warn
  band (e.g. >25% degradation) — never absolute wall-time thresholds.
- Smallest acceptable: `factory/benchmarks/runtime_benchmark.py`
  generating synthetic OTLP at 10k/100k/1M (5M/10M optional flag),
  measuring the §22 metrics, writing `factory/runs/runtime-benchmark-
  <stamp>.json` with env record + comparison vs prior record.

# Context

§22 metrics: wall time, CPU time, peak memory, records/sec, MB/sec,
trace completion rate, unknown rate; sizes 10k→10M; regression warning
on degradation, thresholds robust across machines. §23: initial goal
1M spans <300-500MB <2-4min; later <250MB <60-120s — record honestly,
record hardware.

# Acceptance Criteria

- Benchmark script deterministic-input (seeded generator, no clock in
  data), streams through `load_runtime_project` new path.
- Metrics per size: wall_s, cpu_s, peak_mb, spans, mb_in, spans/sec,
  mb/sec, trace_completion_rate, unknown_rate.
- Env record: python version, platform, cpu count, ram (where
  available via stdlib), tool_version.
- Comparison mode: vs latest `factory/runs/runtime-benchmark-*.json`,
  emits per-metric deltas + `regression: true` when spans/sec or
  peak-mb-per-1k-spans degrades >25%.
- Record for the new streaming path committed under factory/runs/.
- pytest/ruff/mypy pass.

# Constraints

- Deterministic synthetic data; never fabricated numbers.
- Benchmark code lives in factory/, not src/ (no runtime surface).
