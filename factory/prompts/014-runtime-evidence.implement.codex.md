You are implementing Loop Factory spec `014-runtime-evidence`.

        Native adapter: `codex`
        Spec path: `E:\projetos\forge-doctor-api\factory\specs\active\014-runtime-evidence.md`
        Spec hash: `427b55e67d2bf77f9ef679b310c52be5aca87e9412440e9a1dc400191bcc5f81`

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

- Owner: project owner; decisions sourced from §30, §31, §32, §84, §85, §86, §171, §173, §197.
- Problem: runtime evidence plane — static analysis alone can't confirm latency/fanout/N+1 (§102).
- Out of scope: performance regression analysis (016), incident correlation (021), live collectors/agents.
- Review failure: raw trace bodies retained (§173 forbids), non-streaming ingestion on huge exports (§171), weak format detection.
- Riskiest assumption: first-pass format coverage — RESOLVED: OTLP JSON traces first (§197 vendor-neutral), NGINX/Envoy access-log second for request summaries. Jaeger/Zipkin/gateway/cloud formats come later via the `RuntimeArtifactAdapter` contract, not ad-hoc.
- Smallest acceptable: `RuntimeArtifact` adapters (OTLP first) → `TraceModel`/`Span` + observability signals, streaming readers, summary-only retention.

# Context

Runtime artifacts are offline exports only (§30): access logs, structured app logs, OTEL exports, Jaeger, Zipkin, gateway logs, Envoy, NGINX, ALB, cloud gateway exports. First format is OpenTelemetry — vendor-neutral (§197). `TraceModel` (§31): trace_id, spans, root_service, duration, critical_path, errors, attributes. `Span` (§32): service, operation, parent, duration, status, kind, attributes, evidence. Observability model (§84) detects structured logs/metrics/tracing/correlation IDs/request IDs/trace propagation evidence → OBSAPI### checks (§85). Streaming readers required (§171); store summaries, not full raw traces (§173).

# Acceptance Criteria

- `RuntimeArtifactAdapter` contract (mirrors §192 discipline): format detection gate + streaming reader + normalization to `Span`/`TraceModel`.
- OTLP JSON trace export adapter first (§86): resource attributes, `service.name`, `http.route`, `rpc.service`, `rpc.method` mapped.
- One log-format adapter (suggest Envoy/NGINX access log) producing request summaries.
- `TraceModel`/`Span` per §31–§32 with `evidence` linking back to source artifact offsets.
- Streaming ingestion for large exports (§171); summarized retention by default — full raw spans only on explicit request (§173).
- `ApiObservabilityModel` (§84) + checks OBSAPI001–005 (§85): missing request-correlation evidence; trace-propagation gap; inconsistent operation naming; error without structured context; missing latency metrics for critical operation.
- Tests per §202 + §170-scale smoke (10k spans processed without loading whole file in memory).
- `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src` pass.

# Constraints

- Offline exports only — never connect to telemetry backends (§1, §30).
- Secrets redaction applies to ingested attributes (§57, §125).
- Deterministic normalization — same export → same model.

# Review Notes

- Verify detection gate rejects OTLP-looking-but-invalid JSON (§101 analog).
- Confirm critical_path computation is honest — record UNKNOWN when span tree is incomplete.
