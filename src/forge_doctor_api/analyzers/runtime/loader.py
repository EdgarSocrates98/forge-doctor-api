"""Runtime artifact loading: adapter detection + trace/observability models.

Detection is strong-marker only (§101 analog); artifacts that match no
adapter are ignored (recorded nowhere). Ingestion is streaming (§171) and
summary-first by default (§173) — pass `keep_spans=True` to retain full
span records.
"""

from __future__ import annotations

from collections import defaultdict
from typing import BinaryIO

from forge_doctor_api.analyzers.runtime.accesslog import AccessLogAdapter
from forge_doctor_api.analyzers.runtime.adapter import RuntimeArtifactAdapter
from forge_doctor_api.analyzers.runtime.model import (
    ApiObservabilityModel,
    RequestSummary,
    Span,
    SpanStatus,
    TraceModel,
)
from forge_doctor_api.analyzers.runtime.otlp import OtlpJsonAdapter
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import UnknownFact

ADAPTERS = (OtlpJsonAdapter(), AccessLogAdapter())

_CORRELATION_KEYS = (
    "traceparent",
    "x-request-id",
    "x-correlation-id",
    "request_id",
    "trace_id",
    "b3",
)


def _detect(path: str, head: bytes) -> RuntimeArtifactAdapter | None:
    for adapter in ADAPTERS:
        if adapter.detect(path, head):
            return adapter
    return None


def _stream(context: ProjectContext, path: str) -> BinaryIO | None:
    try:
        return context.open_binary(path)
    except OSError:
        return None


def build_traces(
    spans: list[Span], *, keep_spans: bool = False
) -> tuple[TraceModel, ...]:
    """Group spans by trace_id -> §31 TraceModel with honest critical path."""
    by_trace: dict[str, list[Span]] = defaultdict(list)
    for s in spans:
        by_trace[s.trace_id or "(none)"].append(s)

    traces: list[TraceModel] = []
    for trace_id in sorted(by_trace):
        ts = sorted(
            by_trace[trace_id],
            key=lambda s: (s.evidence[0].line or 0 if s.evidence else 0, s.operation),
        )
        roots = [s for s in ts if not s.parent_id]
        ids = {s.span_id for s in ts}
        incomplete = any(s.parent_id and s.parent_id not in ids for s in ts)
        errors = sum(1 for s in ts if s.status is SpanStatus.ERROR)
        duration = (
            max((s.duration_ms or 0) for s in ts) if ts else None
        )
        unknowns: list[UnknownFact] = []
        if incomplete or len(roots) != 1:
            unknowns.append(
                UnknownFact(
                    subject=f"trace {trace_id}",
                    missing="a complete span tree (single root, all parents "
                    "present)",
                    resolution="critical_path is recorded only for complete trees",
                )
            )
            critical: tuple[str, ...] = ()
        else:
            critical = _critical_path(roots[0], ts)
        root_svc = roots[0].service if len(roots) == 1 else None
        traces.append(
            TraceModel(
                trace_id=trace_id,
                spans=tuple(ts) if keep_spans else (),
                root_service=root_svc,
                duration_ms=duration,
                critical_path=critical,
                errors=errors,
                span_count=len(ts),
                incomplete=incomplete or len(roots) != 1,
                unknowns=tuple(unknowns),
            )
        )
    return tuple(traces)


def _critical_path(root: Span, spans: list[Span]) -> tuple[str, ...]:
    """Greedy longest-duration chain root->leaf (deterministic)."""
    children: dict[str | None, list[Span]] = defaultdict(list)
    for s in spans:
        children[s.parent_id].append(s)
    path = [root.operation]
    node = root
    while True:
        kids = children.get(node.span_id, [])
        if not kids:
            return tuple(path)
        node = max(kids, key=lambda s: (s.duration_ms or 0, s.operation))
        path.append(node.operation)


def build_observability(
    spans: list[Span], summaries: list[RequestSummary]
) -> ApiObservabilityModel:
    """§84 signal aggregation from runtime records."""
    signals: dict[str, int] = defaultdict(int)
    corr_keys: set[str] = set()
    errors_no_ctx = 0
    no_duration = 0
    span_ids = {s.span_id for s in spans}
    orphans = sum(
        1 for s in spans if s.parent_id and s.parent_id not in span_ids
    )
    names: set[str] = set()

    for s in spans:
        signals["tracing"] += 1
        names.add(s.operation)
        if s.duration_ms is None:
            no_duration += 1
        else:
            signals["metrics"] += 1
        for k in _CORRELATION_KEYS:
            if k in s.attributes or k in {a.lower() for a in s.attributes}:
                signals["correlation_ids"] += 1
                corr_keys.add(k)
        if s.parent_id or any(
            k in s.attributes for k in ("traceparent", "b3")
        ):
            signals["trace_propagation"] += 1
        if s.status is SpanStatus.ERROR and not any(
            k in s.attributes
            for k in ("error", "error.type", "error.message", "exception.type",
                      "otel.status_description")
        ):
            errors_no_ctx += 1

    for r in summaries:
        signals["structured_logs"] += 1
        if r.request_id:
            signals["request_ids"] += 1
        if r.trace_id:
            signals["trace_propagation"] += 1
        if r.duration_ms is not None:
            signals["metrics"] += 1

    return ApiObservabilityModel(
        signals=dict(sorted(signals.items())),
        correlation_keys=tuple(sorted(corr_keys)),
        operation_names=tuple(sorted(names)),
        error_spans_without_context=errors_no_ctx,
        spans_without_duration=no_duration,
        orphan_spans=orphans,
        request_count=len(summaries),
        span_count=len(spans),
    )


def load_runtime_project(
    context: ProjectContext,
    files: list[str],
    *,
    keep_spans: bool = False,
) -> tuple[tuple[TraceModel, ...], ApiObservabilityModel, tuple[UnknownFact, ...]]:
    """Detect + stream all artifacts -> traces + observability model."""
    all_spans: list[Span] = []
    all_summaries: list[RequestSummary] = []
    unknowns: list[UnknownFact] = []

    for path in sorted(files):
        fh = _stream(context, path)
        if fh is None:
            continue
        with fh:
            head = fh.read(4096)
            adapter = _detect(path, head)
            if adapter is None:
                continue
            fh.seek(0)
            for span in adapter.iter_spans(fh, path):
                all_spans.append(span)
            fh.seek(0)
            for summary in adapter.iter_summaries(fh, path):
                all_summaries.append(summary)

    traces = build_traces(all_spans, keep_spans=keep_spans)
    for t in traces:
        unknowns.extend(t.unknowns)
    obs = build_observability(all_spans, all_summaries)
    return traces, obs, tuple(unknowns)
