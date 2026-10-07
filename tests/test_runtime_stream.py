"""Spec 041 — bounded streaming trace assembly.

TraceAssembler keeps `window` open buckets; evictions emit
incomplete+unknown, never silent drops; ObservabilityAccumulator folds
signals incrementally. Memory is bound by the window + compact results.
"""

from __future__ import annotations

import tracemalloc
from pathlib import Path

from forge_doctor_api.analyzers.runtime.loader import (
    analyze_spans,
    load_runtime_project,
)
from forge_doctor_api.analyzers.runtime.model import (
    Span,
    SpanKind,
)
from forge_doctor_api.analyzers.runtime.stream import TraceAssembler
from forge_doctor_api.core.context import ProjectContext


def _span(
    trace: str,
    span_id: str,
    *,
    parent: str | None = None,
    op: str = "op",
    kind: SpanKind = SpanKind.SERVER,
    dur: float = 10.0,
    line: int = 0,
) -> Span:
    from forge_doctor_api.core.models import Evidence, EvidenceKind

    return Span(
        service="svc",
        operation=op,
        span_id=span_id,
        parent_id=parent,
        trace_id=trace,
        duration_ms=dur,
        kind=kind,
        evidence=(Evidence(
            kind=EvidenceKind.RUNTIME, source="t.json",
            summary="s", line=line or 1),),
    )


def _analyze_all(spans: list[Span]):
    """Feed through the assembler exactly as the loader does."""
    asm = TraceAssembler()
    for s in spans:
        asm.add(s)
    return asm.finish()


def test_streaming_matches_batch_on_interleaved_input() -> None:
    spans = [
        _span("b", "b1", line=1),
        _span("a", "a1", line=2),
        _span("b", "b2", parent="b1", kind=SpanKind.CLIENT, line=3),
        _span("a", "a2", parent="a1", kind=SpanKind.CLIENT, line=4),
    ]
    t_traces, t_exec, t_unk = _analyze_all(spans)
    b_traces, b_exec, b_unk = analyze_spans(list(spans))
    assert [t.trace_id for t in t_traces] == [t.trace_id for t in b_traces]
    assert t_traces == b_traces
    assert t_exec == b_exec
    assert t_unk == b_unk


def test_evicted_trace_emits_incomplete_plus_unknown() -> None:
    asm = TraceAssembler(window=2)
    asm.add(_span("t1", "s1"))
    asm.add(_span("t2", "s2"))
    asm.add(_span("t3", "s3"))  # evicts t1 (LRU oldest)
    traces, _exec, _unknowns = asm.finish()
    t1 = next(t for t in traces if t.trace_id == "t1")
    assert t1.incomplete is True
    assert any("evicted" in u.missing for u in t1.unknowns)
    # t2/t3 flush complete
    assert all(
        t.incomplete is False for t in traces if t.trace_id != "t1")


def test_late_spans_for_evicted_trace_are_counted() -> None:
    asm = TraceAssembler(window=1)
    asm.add(_span("t1", "s1"))
    asm.add(_span("t2", "s2"))  # evicts t1
    asm.add(_span("t1", "s3"))  # late span -> tombstone count
    traces, _exec, unknowns = asm.finish()
    assert any("1 span(s)" in u.missing for u in unknowns)
    t1s = [t for t in traces if t.trace_id == "t1"]
    assert len(t1s) == 1  # tombstoned, not re-opened


def test_output_order_is_sorted_not_arrival() -> None:
    asm = TraceAssembler(window=2)
    for tid in ("c", "a", "b"):
        asm.add(_span(tid, f"{tid}1"))
    traces, _e, _u = asm.finish()
    assert [t.trace_id for t in traces] == ["a", "b", "c"]


def test_max_spans_per_trace_caps_retention() -> None:
    asm = TraceAssembler(keep_spans=True, max_spans_per_trace=1)
    asm.add(_span("t", "s1", line=1))
    asm.add(_span("t", "s2", kind=SpanKind.CLIENT, parent="s1", line=2))
    traces, _e, _unknowns = asm.finish()
    assert len(traces[0].spans) == 1
    assert traces[0].span_count == 2
    assert any("max_spans_per_trace" in u.missing
               for u in traces[0].unknowns)


def test_empty_input() -> None:
    traces, execs, unknowns = TraceAssembler().finish()
    assert traces == execs == unknowns == ()


def _gen_spans(traces: int, per_trace: int):
    """Interleaved generator — nothing materialized outside the assembler."""
    for t in range(traces):
        for s in range(per_trace):
            yield _span(
                f"trace-{t:05d}", f"s{t}-{s}",
                parent=f"s{t}-{s - 1}" if s else None,
                kind=SpanKind.SERVER if s == 0 else SpanKind.CLIENT,
                line=t * per_trace + s,
            )


def _many_spans(traces: int, per_trace: int) -> list[Span]:
    return list(_gen_spans(traces, per_trace))


def test_memory_bound_scales_with_window_not_dataset() -> None:
    """Grow the dataset 4x: peak must grow strictly sub-linearly
    (exponent < 1) — transient span retention is window-bound; only
    compact result models scale with observed data."""
    import math

    def peak(per_trace: int) -> int:
        asm = TraceAssembler(window=20)
        tracemalloc.start()
        for s in _gen_spans(2_000, per_trace):
            asm.add(s)
        asm.finish()
        _cur, pk = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert len(asm._open) <= 20  # structural invariant
        return pk

    small = peak(2)     # 4_000 spans
    large = peak(8)     # 16_000 spans (4x dataset)
    alpha = math.log(large / small) / math.log(4)
    assert alpha < 1.0, f"peak scaled ~N^{alpha:.2f} (must be sublinear)"


def test_child_before_parent_arrival_still_completes() -> None:
    """Out-of-order within a trace: the bucket holds spans until flush,
    so a child arriving before its parent still forms one complete
    tree with a critical path."""
    asm = TraceAssembler(window=4)
    asm.add(_span("t", "s2", parent="s1", kind=SpanKind.CLIENT, line=1))
    asm.add(_span("t", "s3", parent="s2", kind=SpanKind.CLIENT, line=2))
    asm.add(_span("t", "s1", line=3))  # root arrives last
    traces, execs, _unknowns = asm.finish()
    assert len(traces) == 1
    assert traces[0].incomplete is False
    assert traces[0].critical_path == ("op", "op", "op")
    assert len(execs) == 1


def test_missing_parent_marks_trace_incomplete() -> None:
    """A span parented outside its trace is malformed: the trace is
    emitted incomplete with an unknown, never silently repaired."""
    asm = TraceAssembler(window=4)
    asm.add(_span("t", "s1"))
    asm.add(_span("t", "s2", parent="ghost", kind=SpanKind.CLIENT))
    traces, _execs, _unknowns = asm.finish()
    assert traces[0].incomplete is True
    assert traces[0].critical_path == ()
    assert any("complete span tree" in u.missing
               for u in traces[0].unknowns)
    assert asm.orphan_spans == 1


def test_duplicate_span_ids_are_reported() -> None:
    """Two spans sharing a span_id: an explicit unknown records the
    collision; a dup that parents to itself is malformed and marks the
    trace incomplete instead of hanging the critical-path walk."""
    asm = TraceAssembler(window=4)
    asm.add(_span("t", "s1"))
    asm.add(_span("t", "s1", kind=SpanKind.CLIENT, parent="s1"))
    traces, execs, unknowns = asm.finish()
    assert traces[0].span_count == 2  # both observed, none dropped
    assert any("unique span ids" in u.missing for u in unknowns)
    assert traces[0].incomplete is True  # self-parented dup = broken tree
    assert len(execs) == 1


def test_id_collision_with_two_roots_is_incomplete() -> None:
    """Dup span ids where both are parentless yield two roots — the
    trace is incomplete rather than silently picking one as root."""
    asm = TraceAssembler(window=4)
    asm.add(_span("t", "s1"))
    asm.add(_span("t", "s1", kind=SpanKind.CLIENT, parent=None))
    traces, execs, unknowns = asm.finish()
    assert traces[0].span_count == 2
    assert traces[0].incomplete is True
    assert any("unique span ids" in u.missing for u in unknowns)
    assert len(execs) == 1


def test_tombstone_overflow_is_accounted() -> None:
    """Evictions beyond tombstone_limit are counted + reported. A late
    span for a still-tombstoned id is counted and not reassembled; a
    span for a forgotten id honestly starts a fresh trace."""
    asm = TraceAssembler(window=1, tombstone_limit=2)
    asm.add(_span("t1", "s1"))
    asm.add(_span("t2", "s2"))  # evicts t1 -> tombstone {t1}
    asm.add(_span("t3", "s3"))  # evicts t2 -> tombstone {t1, t2}
    asm.add(_span("t4", "s4"))  # evicts t3 -> tombstone {t2, t3}, t1 out
    asm.add(_span("t3", "s5"))  # t3 tombstoned -> late, counted
    asm.add(_span("t1", "s6"))  # t1 forgotten -> new trace
    traces, _execs, unknowns = asm.finish()
    assert any("tombstone capacity for 2" in u.missing for u in unknowns)
    assert any("1 span(s)" in u.missing and "evicted" in u.missing
               for u in unknowns)
    t3s = [t for t in traces if t.trace_id == "t3"]
    assert len(t3s) == 1  # tombstoned, never reassembled
    t1s = [t for t in traces if t.trace_id == "t1"]
    assert len(t1s) == 2  # evicted t1 + fresh t1 from the forgotten id


def test_loader_bounded_end_to_end(tmp_path: Path) -> None:
    """load_runtime_project on an interleaved export stays bounded."""
    spans = _many_spans(300, 3)
    import json

    def _otlp(spans: list[Span]) -> str:
        objs = [
            {
                "traceId": s.trace_id, "spanId": s.span_id,
                "parentSpanId": s.parent_id or "",
                "name": s.operation, "kind": 1,
                "startTimeUnixNano": "1",
                "endTimeUnixNano": "10000000",
            }
            for s in spans
        ]
        return json.dumps({"resourceSpans": [{
            "resource": {"attributes": [{
                "key": "service.name",
                "value": {"stringValue": "svc"}}]},
            "scopeSpans": [{"spans": objs}]}]})

    (tmp_path / "t.json").write_text(_otlp(spans), encoding="utf-8")
    rt = load_runtime_project(
        ProjectContext.from_root(tmp_path), ["t.json"], window=64)
    assert len(rt.traces) == 300
    assert rt.observability.span_count == 900
