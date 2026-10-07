"""RequestCriticalPath (§34-35) - latency decomposition over a trace.

Total time is decomposed into labeled segments when span shape allows:
`auth`, `service:<name>` self-time, `downstream:<callee>`,
`serialization`. Unattributed time is reported honestly, and incomplete
trees add an `UnknownFact` rather than guessing.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from forge_doctor_api.analyzers.runtime.model import (
    Span,
    SpanKind,
    TraceModel,
)
from forge_doctor_api.core.models import Model, UnknownFact

_AUTH_MARKERS = ("auth", "oauth", "jwt", "token")
_SER_MARKERS = ("serializ", "marshal", "encode", "decode", "codec")


@dataclass(frozen=True, kw_only=True)
class CriticalPathSegment(Model):
    label: str
    duration_ms: float
    share: float


@dataclass(frozen=True, kw_only=True)
class RequestCriticalPath(Model):
    """§35 per-trace latency decomposition."""

    trace_id: str
    total_ms: float | None
    segments: tuple[CriticalPathSegment, ...] = ()
    unattributed_ms: float | None = None
    complete: bool = False
    unknowns: tuple[UnknownFact, ...] = ()


def _classify(span: Span) -> str:
    """Category evidence for a span; downstream calls name their callee."""
    if span.kind in (SpanKind.CLIENT, SpanKind.PRODUCER):
        callee = (
            span.attributes.get("peer.service")
            or span.attributes.get("server.address")
            or span.attributes.get("rpc.service")
            or span.attributes.get("http.host")
            or "(unknown)"
        )
        return f"downstream:{callee}"
    low = f"{span.operation} {' '.join(span.attributes)}".lower()
    if any(k in low for k in _AUTH_MARKERS):
        return "auth"
    if any(k in low for k in _SER_MARKERS):
        return "serialization"
    return f"service:{span.service}"


def critical_path(trace: TraceModel) -> RequestCriticalPath:
    """Decompose a trace into labeled segments.

    `service:<root>` self-time = root duration minus attributed segment
    time. `unattributed_ms` is whatever remains; incomplete trees attach
    an `UnknownFact`.
    """
    spans = list(trace.spans)
    if not spans:
        return RequestCriticalPath(
            trace_id=trace.trace_id,
            total_ms=trace.duration_ms,
            unknowns=(
                UnknownFact(
                    subject=f"trace {trace.trace_id}",
                    missing="spans retained",
                    resolution="load with keep_spans=True",
                ),
            ),
        )
    by_label: dict[str, float] = defaultdict(float)
    service_span_ms: dict[str, float] = defaultdict(float)
    roots = [s for s in spans if not s.parent_id]
    ids = {s.span_id for s in spans}
    complete = (
        not trace.incomplete
        and len(roots) == 1
        and all(not s.parent_id or s.parent_id in ids for s in spans)
    )
    children: dict[str | None, list[Span]] = defaultdict(list)
    for s in spans:
        children[s.parent_id].append(s)

    for s in spans:
        dur = s.duration_ms or 0.0
        label = _classify(s)
        if label.startswith("service:"):
            # self-time = own duration minus children's durations
            kids = children.get(s.span_id, [])
            child_ms = sum(c.duration_ms or 0.0 for c in kids)
            by_label[label] += max(0.0, dur - child_ms)
        else:
            by_label[label] += dur
            service_span_ms[label] = dur

    total = trace.duration_ms
    if total is None:
        total = max((s.duration_ms or 0.0) for s in spans)
    attributed = sum(by_label.values())
    unattributed = max(0.0, total - attributed) if total else None

    segments = tuple(
        CriticalPathSegment(
            label=label,
            duration_ms=ms,
            share=(ms / total) if total else 0.0,
        )
        for label, ms in sorted(by_label.items(), key=lambda kv: -kv[1])
        if ms > 0
    )
    unknowns: list[UnknownFact] = []
    if not complete:
        unknowns.append(
            UnknownFact(
                subject=f"trace {trace.trace_id}",
                missing="a complete span tree",
                resolution="decomposition covers retained spans only; "
                "re-export a complete trace window",
            )
        )
    return RequestCriticalPath(
        trace_id=trace.trace_id,
        total_ms=total,
        segments=segments,
        unattributed_ms=unattributed,
        complete=complete,
        unknowns=tuple(unknowns),
    )
