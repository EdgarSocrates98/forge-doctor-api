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
