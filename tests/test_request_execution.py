"""RequestExecution/DownstreamCall/RequestHistory tests (spec 015, §28-29, §87)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.runtime import (
    RequestExecution,
    RequestHistory,
    RequestSummary,
    Span,
    SpanKind,
    TraceModel,
    executions_from_summaries,
    executions_from_traces,
    runtime_graph,
)
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    RelationshipKind,
)


def _span(
    sid: str,
    tid: str,
    kind: SpanKind,
    service: str = "api",
    operation: str = "op",
    parent: str | None = None,
    dur: float = 100,
    start: int = 1_700_000_000_000_000_000,
    attrs: dict[str, str] | None = None,
) -> Span:
    return Span(
        service=service,
        operation=operation,
        span_id=sid,
        trace_id=tid,
        parent_id=parent,
        start_unix_nano=start,
        duration_ms=dur,
        kind=kind,
        attributes=attrs or {},
        evidence=(Evidence(kind=EvidenceKind.RUNTIME, source="t.json", summary=sid),),
    )


def _trace(spans: list[Span]) -> TraceModel:
    return TraceModel(
        trace_id=spans[0].trace_id or "t",
        spans=tuple(spans),
        span_count=len(spans),
    )


def test_server_span_to_execution() -> None:
    spans = [
        _span("srv", "t1", SpanKind.SERVER, attrs={
            "http.request.method": "GET",
            "http.route": "/users",
            "http.status_code": "200",
            "x-request-id": "r-1",
            "http.response.body.size": "1234",
        }),
    ]
    ex, unk = executions_from_traces((_trace(spans),))
    assert len(ex) == 1
    e = ex[0]
    assert e.service == "api" and e.method == "GET" and e.route == "/users"
    assert e.status == "200" and e.request_id == "r-1" and e.response_bytes == 1234
    assert e.start_unix_nano == 1_700_000_000_000_000_000
    assert not unk


def test_client_span_becomes_downstream_call() -> None:
    spans = [
        _span("srv", "t1", SpanKind.SERVER),
        _span("cli", "t1", SpanKind.CLIENT, parent="srv", dur=50, attrs={
            "peer.service": "pg",
            "http.resend_count": "2",
            "rpc.system": "grpc",
        }),
    ]
    ex, _ = executions_from_traces((_trace(spans),))
    (call,) = ex[0].downstream_calls
    assert call.caller == "api" and call.callee == "pg"
    assert call.retries == 2 and call.protocol == "grpc"
    assert call.duration_ms == 50


def test_observed_retries_distinct_from_policy() -> None:
    """Review note: retries field is observed resends, never configured policy."""
    spans = [
        _span("srv", "t1", SpanKind.SERVER),
        _span("cli", "t1", SpanKind.CLIENT, parent="srv",
              attrs={"x-envoy-attempt-count": "3"}),
    ]
    ex, _ = executions_from_traces((_trace(spans),))
    assert ex[0].downstream_calls[0].retries == 2  # attempts - 1


def test_missing_fields_stay_unknown() -> None:
    spans = [_span("srv", "t1", SpanKind.SERVER)]
    ex, _ = executions_from_traces((_trace(spans),))
    e = ex[0]
    assert e.request_id is None and e.method is None
    assert e.request_bytes is None and e.cache_status is None
    assert e.retries is None and e.downstream_calls == ()


def test_no_server_root_fallback() -> None:
    """No SERVER span -> tree root produces the execution."""
    spans = [_span("r", "t1", SpanKind.INTERNAL, operation="root_op")]
    ex, _ = executions_from_traces((_trace(spans),))
    assert len(ex) == 1 and ex[0].operation == "root_op"


def test_broken_parent_attaches_to_root_with_unknown() -> None:
    spans = [
        _span("srv", "t1", SpanKind.SERVER),
        _span("cli", "t1", SpanKind.CLIENT, parent="ghost",
              attrs={"peer.service": "db"}),
    ]
    ex, unk = executions_from_traces((_trace(spans),))
    assert len(ex[0].downstream_calls) == 1
    assert unk and "incomplete" in unk[0].resolution


def test_access_log_summary_to_execution() -> None:
    summaries = (
        RequestSummary(
            method="GET", path="/users", status=200, request_id="r-9",
            bytes_sent=512,
            evidence=(Evidence(kind=EvidenceKind.RUNTIME, source="a.log",
                               summary="line 1", line=1),),
        ),
    )
    ex, _ = executions_from_summaries(summaries)
    e = ex[0]
    assert e.method == "GET" and e.route == "/users" and e.status == "200"
    assert e.service is None  # never fabricated
    assert e.response_bytes == 512
    assert any("service identity" in u.missing for u in e.unknowns)


def test_history_keyed_windows_deterministic() -> None:
    base = 1_700_000_000_000_000_000
    exs = (
        RequestExecution(request_id="b", trace_id="t2", service="api",
                         operation="op", start_unix_nano=base + 60),
        RequestExecution(request_id="a", trace_id="t1", service="api",
                         operation="op", start_unix_nano=base),
        RequestExecution(request_id="c", trace_id="t3", service="api",
                         operation="op",
                         start_unix_nano=base + 3_700_000_000_000),
    )
    h = RequestHistory()
    h.add_all(tuple(reversed(exs)))
    windows = h.windows()
    assert windows == ("2023-11-14T22", "2023-11-14T23")
    assert h.count() == 3
    first_hour = h.query(service="api", window="2023-11-14T22")
    assert [e.request_id for e in first_hour] == ["a", "b"]
    assert h.query(service="api", window="2023-11-14T23")[0].request_id == "c"
    assert h.query(service="other") == ()


def test_history_unwindowed_and_iteration() -> None:
    h = RequestHistory()
    h.add(RequestExecution(request_id=None, trace_id=None, service=None,
                           operation="op"))
    assert h.windows() == ("(unwindowed)",)
    assert h.keys() == (("(unknown)", "op", "(unwindowed)"),)


def test_runtime_graph_calls_and_retries() -> None:
    spans = [
        _span("srv", "t1", SpanKind.SERVER),
        _span("cli", "t1", SpanKind.CLIENT, parent="srv",
              attrs={"peer.service": "pg", "http.resend_count": "1"}),
        _span("cli2", "t1", SpanKind.CLIENT, parent="srv",
              attrs={"peer.service": "cache"}),
    ]
    ex, _ = executions_from_traces((_trace(spans),))
    g = runtime_graph(ex)
    kinds = {(r.kind, r.source_id, r.target_id) for r in g.relationships()}
    svc = "service:runtime:"
    assert (RelationshipKind.CALLS, f"{svc}api", f"{svc}pg") in kinds
    assert (RelationshipKind.CALLS, f"{svc}api", f"{svc}cache") in kinds
    assert (RelationshipKind.RETRIES, f"{svc}api", f"{svc}pg") in kinds
    assert not any(
        k == RelationshipKind.RETRIES and t == f"{svc}cache"
        for k, _, t in kinds
    )
    for r in g.relationships():
        assert r.evidence[0].kind is EvidenceKind.RUNTIME


def test_determinism_repeat_runs() -> None:
    spans = [
        _span("srv", "t1", SpanKind.SERVER, attrs={"x-request-id": "r1"}),
        _span("cli", "t1", SpanKind.CLIENT, parent="srv",
              attrs={"peer.service": "pg"}),
    ]
    a = executions_from_traces((_trace(spans),))[0]
    b = executions_from_traces((_trace(spans),))[0]
    assert [e.to_dict() for e in a] == [e.to_dict() for e in b]


def test_large_volume_history(tmp_path: Path) -> None:
    """10k executions across windows stay queryable and ordered."""
    base = 1_700_000_000_000_000_000
    h = RequestHistory()
    for i in range(10_000):
        h.add(
            RequestExecution(
                request_id=f"r{i:05d}",
                trace_id=f"t{i}",
                service="api" if i % 2 else "web",
                operation=f"op{i % 7}",
                start_unix_nano=base + i * 3_600_000_000_000 // 100,
            )
        )
    assert h.count() == 10_000
    assert len(h.query(service="api")) == 5_000
    wins = h.windows()
    assert wins == tuple(sorted(wins))
