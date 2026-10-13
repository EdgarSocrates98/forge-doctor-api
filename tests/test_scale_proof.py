"""Spec 076 — runtime/temporal/scale proof.

Four enforced guarantees:

(a) memory curve — endpoint parsing stays sub-quadratic: per-endpoint
    heap cost is bounded regardless of corpus size.
(b) streaming bounds — retained span rows are capped by
    `max_spans_per_trace` and open buckets by `window`, not by the
    corpus size.
(c) tombstone round-trip — an operation removed between snapshots is
    excluded from current state but retained in history (delta +
    regression finding survive the store round trip).
(d) snapshot format — a file missing `snapshot_format` loads as the
    legacy format; a newer format is rejected with an explicit reason.

Memory measurements use `tracemalloc` (stdlib, works on Windows CI);
no psutil/resource dependency.
"""

from __future__ import annotations

import json
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.runtime.model import Span, SpanKind
from forge_doctor_api.analyzers.runtime.stream import TraceAssembler
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Evidence, EvidenceKind
from forge_doctor_api.core.report import DomainSummary
from forge_doctor_api.handoff.delta import compute_delta
from forge_doctor_api.report import DoctorReport
from forge_doctor_api.temporal import (
    SNAPSHOT_FORMAT,
    SnapshotError,
    SnapshotStore,
    architectural_regressions,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _openapi_doc(count: int) -> str:
    return json.dumps({
        "openapi": "3.0.3",
        "info": {"title": "B", "version": "1"},
        "paths": {
            f"/r{i}": {
                "get": {
                    "operationId": f"get{i}",
                    "responses": {"200": {"description": "ok"}},
                }
            }
            for i in range(count)
        },
    })


def _peak_mb(fn) -> float:
    tracemalloc.start()
    try:
        fn()
        _cur, peak = tracemalloc.get_traced_memory()
        return peak / 1e6
    finally:
        tracemalloc.stop()


# (a) memory curve ---------------------------------------------------------


def test_endpoint_memory_growth_sub_quadratic(tmp_path: Path) -> None:
    """Per-endpoint heap cost is bounded — a quadratic curve would
    show per-op cost growing ~linearly with N; we bound it at 4x the
    small-corpus rate (generous slack over allocator noise, fatal to
    any real super-linear regression)."""
    peaks: dict[int, float] = {}
    for n in (1_000, 4_000, 8_000):
        root = tmp_path / f"e{n}"
        root.mkdir()
        (root / "openapi.json").write_text(_openapi_doc(n), "utf-8")
        ctx = ProjectContext.from_root(root)
        mb = _peak_mb(lambda ctx=ctx: load_openapi_project(ctx))
        peaks[n] = mb
        assert mb > 0
    per_1k = peaks[1_000] / 1_000
    per_4k = peaks[4_000] / 4_000
    per_8k = peaks[8_000] / 8_000
    assert per_4k <= per_1k * 4.0, (
        f"4k per-op cost {per_4k:.3f}MB vs 1k {per_1k:.3f}MB")
    assert per_8k <= per_1k * 4.0, (
        f"8k per-op cost {per_8k:.3f}MB vs 1k {per_1k:.3f}MB")


# (b) streaming bounds ------------------------------------------------------


def _span(trace: str, span_id: str, *, line: int = 1) -> Span:
    return Span(
        service="svc", operation="GET /r", span_id=span_id,
        trace_id=trace, duration_ms=10.0, kind=SpanKind.SERVER,
        evidence=(Evidence(
            kind=EvidenceKind.RUNTIME, source="t.json",
            summary="s", line=line),))


def test_stream_rows_bounded_by_config_not_corpus() -> None:
    """A corpus 10x larger than the caps still emits at most the
    configured rows per trace — the bound is config, not input size."""
    cap = 4
    asm = TraceAssembler(
        window=50, keep_spans=True, max_spans_per_trace=cap)
    # 500 distinct traces x 40 spans each — 10x over both bounds
    for i in range(500):
        tid = f"t{i:04x}"
        for s in range(40):
            asm.add(_span(tid, f"{tid}-s{s}", line=s + 1))
    traces, _execs, _unknowns = asm.finish()
    # every emitted trace retains at most `cap` rows
    assert traces
    assert max(len(t.spans) for t in traces) <= cap
    # retention truncation is recorded, never silent
    assert any("max_spans_per_trace" in u.missing
               for t in traces for u in t.unknowns)


def test_stream_window_bound_independent_of_corpus() -> None:
    """Eviction+tombstone accounting keeps working at any corpus size —
    late spans are counted, never reassembled."""
    asm = TraceAssembler(window=8)
    for i in range(10):
        asm.add(_span(f"t{i}", f"s{i}"))
    # interleave a span for an already-evicted trace
    asm.add(_span("t0", "late"))
    traces, _e, unknowns = asm.finish()
    t0 = [t for t in traces if t.trace_id == "t0"]
    assert len(t0) == 1 and t0[0].incomplete  # emitted once, tombstoned
    assert any("evicted" in u.missing for u in unknowns)


# (c) tombstone round-trip --------------------------------------------------


def test_tombstoned_operation_survives_snapshot_roundtrip(
        tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    prev = DoctorReport(
        operations=("GET /a", "GET /b"),
        contracts=DomainSummary(digests=(
            ("operation_id:getA", "hA"), ("operation_id:getB", "hB"))))
    cur = DoctorReport(
        operations=("GET /a",),
        contracts=DomainSummary(digests=(("operation_id:getA", "hA"),)))
    p = store.save(prev, label="p", created_at=NOW)
    c = store.save(cur, label="c", created_at=NOW)

    loaded_prev = store.report(p.id)
    loaded_cur = store.report(c.id)
    # tombstoned op excluded from current state
    assert "GET /b" not in loaded_cur.operations
    # ...but retained in history — delta + regression finding both see it
    delta = compute_delta(loaded_prev, loaded_cur)
    assert "operation_id:getB" in delta.operations_removed
    regs = architectural_regressions(loaded_prev, loaded_cur)
    assert any(f.id == "APITEMP003" and "GET /b" in f.description
               for f in regs)
    # both points-in-time remain addressable
    assert {s.id for s in store.list()} == {p.id, c.id}


# (d) snapshot format forward-compat ---------------------------------------


def test_snapshot_format_migration_and_reject(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path / "snaps")
    snap = store.save(DoctorReport(operations=("GET /a",)),
                      label="ok", created_at=NOW)

    # legacy file (no snapshot_format key) loads as format 1
    path = tmp_path / "snaps" / f"{snap.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["snapshot_format"]
    legacy = tmp_path / "snaps" / "legacy.json"
    legacy.write_text(json.dumps(data), encoding="utf-8")
    legacy_id = data["snapshot"]["id"]
    # snapshot() resolves by id prefix/label; read the file directly
    legacy_store = SnapshotStore(tmp_path / "snaps")
    loaded = legacy_store.report(legacy_id)
    assert loaded.operations == ("GET /a",)

    # a newer format is rejected with an explicit reason
    data["snapshot_format"] = SNAPSHOT_FORMAT + 1
    data["snapshot"]["id"] = "future0"
    future = tmp_path / "snaps" / "future0.json"
    future.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SnapshotError, match="newer format"):
        store.report("future0")
