---
id: 043-runtime-benchmark
title: Runtime benchmark suite + regression gate with environment record
agent: claude
risk: low
grill: completed
verification:
  - python -m pytest -q
  - python -m ruff check .
  - python -m mypy src
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
