# Runtime evidence

The engine ingests *exported* runtime artifacts — it never connects to a
live system. Supported inputs are detected by content, not filename:

- **OTLP/OTEL JSON** — `resourceSpans[].scopeSpans[].spans[]` with
  `http.method`/`http.route`/`http.status_code`-style attributes.
- **Access logs** — nginx/combined-style request lines.

Everything flows through `load_runtime_project(context, files)` which
produces `TraceModel`s, an `ApiObservabilityModel`, and explicit
`UnknownFact`s for unparseable content.

## Compact storage, no raw traces

Raw spans are **not retained** by default: `keep_spans=False` drops them
after parsing. With `keep_spans=True`, spans live only inside the
in-memory `TraceModel` for normalization into `RequestExecution` — the
§28 summary record (service, operation, method, route, duration, status,
bytes, retries, downstream calls, evidence). `RequestHistory` stores
these executions keyed by `service + operation + window`; serialized
output never contains OTLP payload fields
(`tests/test_offline.py` proves both).

## Derived models

- `executions_from_traces(traces)` → `RequestExecution` per request,
  with `DownstreamCall` edges reconstructed from span parentage and
  `peer.service` attributes.
- `build_baselines(executions)` → per-endpoint latency/error baselines.
- `run_perf_checks(executions)` → `APIPERF###` regression findings.
- `run_observability_checks(model)` → `OBSAPI###` findings (correlation
  gaps, propagation gaps, naming inconsistencies, unstructured errors,
  missing latency metrics).
- `error_budget` / SLO helpers in `reliability/slo.py` evaluate declared
  objectives against observed windows — and stay silent when a window
  has insufficient samples rather than emitting a noisy verdict.
- `fanout_signals(routes, clients, executions)` → `FanoutSignal` (§59):
  per-operation dependency width. Static tier counts distinct call-site
  targets in a handler's source file (multi-handler files record an
  attribution `UnknownFact` instead of guessing); runtime tier counts
  distinct callees in `downstream_calls` → `CONFIRMED`. Runtime evidence
  outranks static per §102 — a static count is never presented as
  confirmed, and a caller-requested subject with no evidence yields an
  explicit `CANDIDATE` row with `None` widths rather than no row.

## Scale

Ingestion is exercised at 10k spans in `tests/test_offline.py` and
benchmarked at 10k/100k/1M spans by
`factory/benchmarks/scale_benchmark.py` (record:
`factory/runs/scale-benchmark.json`).

## Example

```bash
forge-doctor-api runtime requests ./evidence       # normalized executions
forge-doctor-api runtime baseline ./evidence       # p50/p95/p99 per route
forge-doctor-api runtime regressions ./evidence    # APIPERF findings
```
