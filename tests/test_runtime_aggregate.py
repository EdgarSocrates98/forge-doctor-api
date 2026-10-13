"""Spec 042 — online runtime aggregation over execution streams."""

from __future__ import annotations

from forge_doctor_api.analyzers.runtime.aggregate import (
    aggregate_executions,
    aggregate_summaries,
)
from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.analyzers.runtime.model import RequestSummary
from forge_doctor_api.checks.perf.engine import run_perf_checks

HOUR = 3_600_000_000_000


def _exec(
    op: str = "GET /x",
    *,
    service: str | None = "svc",
    dur: float | None = 10.0,
    status: str | None = "200",
    start: int | None = HOUR,
    retries: int | None = None,
    downstream: int = 0,
    req: int | None = None,
    resp: int | None = None,
    timed_out: bool | None = None,
) -> RequestExecution:
    from forge_doctor_api.analyzers.runtime.execution import DownstreamCall

    return RequestExecution(
        request_id=None,
        trace_id="t",
        service=service,
        operation=op,
        start_unix_nano=start,
        duration_ms=dur,
        status=status,
        request_bytes=req,
        response_bytes=resp,
        retries=retries,
        timed_out=timed_out,
        downstream_calls=tuple(
            DownstreamCall(caller=service, callee="db", operation="q")
            for _ in range(downstream)
        ),
    )


def test_aggregates_per_operation() -> None:
    ex = [
        _exec(dur=10.0), _exec(dur=20.0), _exec(dur=30.0, status="500"),
        _exec(op="POST /y", dur=5.0, retries=2, downstream=3),
    ]
    agg = aggregate_executions(ex)
    assert agg.executions == 4
    assert not agg.approximate
    ops = {o.operation: o for o in agg.operations}
    x = ops["GET /x"]
    assert x.requests == 3 and x.errors == 1
    assert x.error_rate is not None and abs(x.error_rate - 1 / 3) < 1e-9
    assert x.latency_ms.p50 == 20.0 and x.latency_ms.count == 3
    y = ops["POST /y"]
    assert y.retries_observed == 2
    assert y.downstream_calls == 3
    assert y.fanout_per_request == 3.0


def test_iterator_in_same_result() -> None:
    ex = [_exec(dur=10.0), _exec(dur=20.0)]
    assert aggregate_executions(iter(ex)) == aggregate_executions(tuple(ex))


def test_cap_hit_marks_approximate() -> None:
    ex = [_exec(dur=float(i)) for i in range(10)]
    agg = aggregate_executions(ex, cap=4)
    assert agg.approximate
    lat = agg.operations[0].latency_ms
    assert lat.approximate and lat.cap == 4
    assert lat.count == 10  # true count kept; sample bounded


def test_reservoir_is_deterministic() -> None:
    ex = [_exec(dur=float(i)) for i in range(200)]
    a = aggregate_executions(ex, cap=10)
    b = aggregate_executions(list(ex), cap=10)
    assert a == b


def test_empty_input() -> None:
    agg = aggregate_executions(())
    assert agg.executions == 0 and agg.operations == ()
    assert aggregate_summaries(()) == ()


def test_window_counters() -> None:
    ex = [
        _exec(start=HOUR),
        _exec(start=HOUR),
        _exec(start=2 * HOUR),
        _exec(start=None),
    ]
    ops = aggregate_executions(ex).operations
    windows = dict(ops[0].windows)
    assert windows["(unwindowed)"] == 1
    assert sum(windows.values()) == 4


def test_summary_aggregation() -> None:
    rows = [
        RequestSummary(method="GET", path="/a", status=200,
                       duration_ms=10.0),
        RequestSummary(method="GET", path="/a", status=200,
                       duration_ms=30.0),
        RequestSummary(method="GET", path="/b", status=200,
                       duration_ms=None),
    ]
    out = dict(aggregate_summaries(rows))
    assert set(out) == {"/a"}
    assert out["/a"].count == 2
    assert out["/a"].p50 == 20.0


def test_perf_checks_accept_iterators() -> None:
    base = [_exec(dur=10.0, start=HOUR) for _ in range(10)]
    cur = [_exec(dur=100.0, start=2 * HOUR) for _ in range(10)]
    via_tuple = run_perf_checks(tuple(base + cur))
    via_iter = run_perf_checks(iter(base + cur))
    assert via_tuple == via_iter
