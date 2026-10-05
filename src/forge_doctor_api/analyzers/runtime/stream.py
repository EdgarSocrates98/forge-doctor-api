"""§19-§21 bounded streaming trace assembly.

Spans arrive in artifact order; `TraceAssembler` keeps at most `window`
open trace buckets (LRU). An evicted bucket still emits its TraceModel —
`incomplete=True` plus an `UnknownFact`, never silently dropped — and
its trace_id is tombstoned so late spans are counted, not reassembled.

Observability counters are folded incrementally by
`ObservabilityAccumulator`; orphan detection is per-trace at emit time
(a span parented outside its own trace is malformed anyway).

Memory is bounded by `window` open buckets plus compact result models —
never by the raw dataset.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict

from forge_doctor_api.analyzers.runtime.execution import (
    RequestExecution,
    executions_for_trace,
)
from forge_doctor_api.analyzers.runtime.model import (
    ApiObservabilityModel,
    RequestSummary,
    Span,
    SpanStatus,
    TraceModel,
)
from forge_doctor_api.core.models import UnknownFact

_TRACELESS = "(none)"
_CORRELATION_KEYS = (
    "traceparent",
    "x-request-id",
    "x-correlation-id",
    "request_id",
    "trace_id",
    "b3",
)
_ERROR_ATTR_KEYS = (
    "error",
    "error.type",
    "error.message",
    "exception.type",
    "otel.status_description",
)


def _sort_key(span: Span) -> tuple[int, str]:
    line = span.evidence[0].line if span.evidence else None
    return (line or 0, span.operation)


class TraceAssembler:
    """Bounded per-trace span assembly feeding compact result models."""

    def __init__(
        self,
        *,
        window: int = 10_000,
        keep_spans: bool = False,
        max_spans_per_trace: int | None = None,
        tombstone_limit: int | None = None,
    ) -> None:
        self._window = max(1, window)
        self._keep_spans = keep_spans
        self._max_spans = max_spans_per_trace
        self._tombstone_limit = max(1, tombstone_limit or window)
        self._open: OrderedDict[str, list[Span]] = OrderedDict()
        self._tombstones: OrderedDict[str, None] = OrderedDict()
        self._traces: list[TraceModel] = []
        self._executions: list[RequestExecution] = []
        self._unknowns: list[UnknownFact] = []
        self._orphan_spans = 0
        self._late_spans = 0
        self._tombstone_overflow = 0

    @property
    def orphan_spans(self) -> int:
        return self._orphan_spans

    def add(self, span: Span) -> None:
        """Fold one span into its trace bucket (bounded)."""
        tid = span.trace_id or _TRACELESS
        if tid in self._tombstones:
            self._late_spans += 1
            return
        bucket = self._open.get(tid)
        if bucket is None:
            if len(self._open) >= self._window:
                self._evict_oldest()
            self._open[tid] = [span]
        else:
            bucket.append(span)
            self._open.move_to_end(tid)

    def finish(
        self,
    ) -> tuple[
        tuple[TraceModel, ...],
        tuple[RequestExecution, ...],
        tuple[UnknownFact, ...],
    ]:
        """Flush remaining buckets (complete traces) and sort output."""
        for tid, spans in self._open.items():
            self._emit(tid, spans, evicted=False)
        self._open.clear()
        if self._late_spans:
            self._unknowns.append(
                UnknownFact(
                    subject="runtime traces",
                    missing=f"{self._late_spans} span(s) for traces already "
                    "evicted from the assembly window",
                    resolution="increase the trace window or pre-sort the "
                    "export by trace_id",
                )
            )
        if self._tombstone_overflow:
            self._unknowns.append(
                UnknownFact(
                    subject="runtime traces",
                    missing="tombstone capacity for "
                    f"{self._tombstone_overflow} evicted trace id(s)",
                    resolution="late spans for these ids may start new "
                    "incomplete traces",
                )
            )
        self._traces.sort(key=lambda t: t.trace_id)
        self._executions.sort(
            key=lambda e: (
                e.start_unix_nano or 0,
                e.request_id or "",
                e.trace_id or "",
                e.service or "",
                e.operation,
            )
        )
        return (
            tuple(self._traces),
            tuple(self._executions),
            tuple(self._unknowns),
        )

    def _evict_oldest(self) -> None:
        tid, spans = self._open.popitem(last=False)
        self._emit(tid, spans, evicted=True)
        self._tombstones[tid] = None
        if len(self._tombstones) > self._tombstone_limit:
            self._tombstones.popitem(last=False)
            self._tombstone_overflow += 1

    def _emit(self, trace_id: str, spans: list[Span], *, evicted: bool) -> None:
        ts = sorted(spans, key=_sort_key)
        executions, exec_unknowns = executions_for_trace(trace_id, ts)
        self._executions.extend(executions)
        self._unknowns.extend(exec_unknowns)

        ids = {s.span_id for s in ts}
        self._orphan_spans += sum(
            1 for s in ts if s.parent_id and s.parent_id not in ids
        )
        roots = [s for s in ts if not s.parent_id]
        broken = any(
            s.parent_id
            and (s.parent_id == s.span_id or s.parent_id not in ids)
            for s in ts)
        incomplete = evicted or broken or len(roots) != 1

        unknowns: list[UnknownFact] = []
        if evicted:
            unknowns.append(
                UnknownFact(
                    subject=f"trace {trace_id}",
                    missing="the complete span set (assembly window evicted "
                    "this trace before the artifact ended)",
                    resolution="increase the trace window or pre-sort the "
                    "export by trace_id",
                )
            )
        if broken or len(roots) != 1:
            unknowns.append(
                UnknownFact(
                    subject=f"trace {trace_id}",
                    missing="a complete span tree (single root, all parents "
                    "present)",
                    resolution="critical_path is recorded only for complete "
                    "trees",
                )
            )
        retained = ts
        if self._keep_spans and self._max_spans is not None and (
            len(ts) > self._max_spans
        ):
            retained = ts[: self._max_spans]
            unknowns.append(
                UnknownFact(
                    subject=f"trace {trace_id}",
                    missing=f"{len(ts) - self._max_spans} span(s) beyond "
                    f"max_spans_per_trace={self._max_spans}",
                    resolution="raise max_spans_per_trace",
                )
            )
        critical: tuple[str, ...] = ()
        if not incomplete:
            critical = _critical_path(roots[0], ts)
        self._traces.append(
            TraceModel(
                trace_id=trace_id,
                spans=tuple(retained) if self._keep_spans else (),
                root_service=roots[0].service if len(roots) == 1 else None,
                duration_ms=max((s.duration_ms or 0) for s in ts)
                if ts
                else None,
                critical_path=critical,
                errors=sum(1 for s in ts if s.status is SpanStatus.ERROR),
                span_count=len(ts),
                incomplete=incomplete,
                unknowns=tuple(unknowns),
            )
        )


def _critical_path(root: Span, spans: list[Span]) -> tuple[str, ...]:
    """Greedy longest-duration chain root->leaf (deterministic)."""
    children: dict[str | None, list[Span]] = defaultdict(list)
    for s in spans:
        children[s.parent_id].append(s)
    path = [root.operation]
    node = root
    seen = {root.span_id}
    while True:
        kids = [s for s in children.get(node.span_id, [])
                if s.span_id not in seen]
        if not kids:
            return tuple(path)
        node = max(kids, key=lambda s: (s.duration_ms or 0, s.operation))
        seen.add(node.span_id)
        path.append(node.operation)


class ObservabilityAccumulator:
    """Incremental §84 signal aggregation over streamed records."""

    def __init__(self) -> None:
        self._signals: dict[str, int] = defaultdict(int)
        self._corr_keys: set[str] = set()
        self._names: set[str] = set()
        self._errors_no_ctx = 0
        self._no_duration = 0
        self._orphan_spans = 0
        self._request_count = 0
        self._span_count = 0

    def add_span(self, s: Span) -> None:
        self._span_count += 1
        self._signals["tracing"] += 1
        self._names.add(s.operation)
        if s.duration_ms is None:
            self._no_duration += 1
        else:
            self._signals["metrics"] += 1
        lowered = {a.lower() for a in s.attributes}
        for k in _CORRELATION_KEYS:
            if k in s.attributes or k in lowered:
                self._signals["correlation_ids"] += 1
                self._corr_keys.add(k)
        if s.parent_id or "traceparent" in s.attributes or (
            "b3" in s.attributes
        ):
            self._signals["trace_propagation"] += 1
        if s.status is SpanStatus.ERROR and not any(
            k in s.attributes for k in _ERROR_ATTR_KEYS
        ):
            self._errors_no_ctx += 1

    def add_summary(self, r: RequestSummary) -> None:
        self._request_count += 1
        self._signals["structured_logs"] += 1
        if r.request_id:
            self._signals["request_ids"] += 1
        if r.trace_id:
            self._signals["trace_propagation"] += 1
        if r.duration_ms is not None:
            self._signals["metrics"] += 1

    def note_orphans(self, count: int) -> None:
        self._orphan_spans += count

    def build(self) -> ApiObservabilityModel:
        return ApiObservabilityModel(
            signals=dict(sorted(self._signals.items())),
            correlation_keys=tuple(sorted(self._corr_keys)),
            operation_names=tuple(sorted(self._names)),
            error_spans_without_context=self._errors_no_ctx,
            spans_without_duration=self._no_duration,
            orphan_spans=self._orphan_spans,
            request_count=self._request_count,
            span_count=self._span_count,
        )
