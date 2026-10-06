"""Performance intelligence tests (spec 016, §33-38, §88-97, §148-155)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.analyzers.runtime import (
    DownstreamCall,
    RequestExecution,
    Span,
    SpanKind,
    TraceModel,
)
from forge_doctor_api.checks.perf import run_perf_checks
from forge_doctor_api.cli import app
from forge_doctor_api.core.models import Confidence, Evidence, EvidenceKind
from forge_doctor_api.perf import (
    ApiLatencyBudget,
    BudgetHop,
    ChangeEvent,
    Constraint,
    Experiment,
    ExperimentVerdict,
    RequestScenario,
    Saturation,
    ThresholdProvenance,
    build_baselines,
    capacity_signals,
    correlate_changes,
    cost_drivers,
    critical_path,
    evaluate_budget,
    evaluate_experiment,
    mad,
    median,
    payload_shape_from_schema,
    percentile,
    performance_signals,
    robust_stats,
)
from forge_doctor_api.perf.baseline import BaselineDimension
from forge_doctor_api.perf.payload import is_large
from forge_doctor_api.perf.signals import PerformanceFamily

BASE = 1_700_000_000_000_000_000
HOUR = 3_600_000_000_000


def _exec(
    i: int,
    w: int,
    dur: float,
    *,
    op: str = "/checkout",
    svc: str = "api",
    status: str = "200",
    retries: int | None = 0,
    timed_out: bool | None = False,
    payload: int | None = 2_000,
    fanout: int = 0,
    callee: str = "payments",
    callee_dur: float = 100,
    cache: str | None = None,
) -> RequestExecution:
    calls = tuple(
        DownstreamCall(
            caller=svc, callee=callee, operation="charge",
            duration_ms=callee_dur, retries=0,
        )
        for _ in range(fanout)
    )
    return RequestExecution(
        request_id=f"r{i}", trace_id=f"t{i}", service=svc, operation=op,
        method="GET", route=op, start_unix_nano=BASE + w * HOUR + i,
        duration_ms=dur, status=status, retries=retries,
        timed_out=timed_out, response_bytes=payload,
        downstream_calls=calls, cache_status=cache,
    )


def _ids(findings) -> set[str]:
    return {f.id for f in findings}


# -- §89 robust stats --------------------------------------------------------


def test_robust_stats() -> None:
    xs = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert median(xs) == 30.0
    assert percentile(xs, 0) == 10.0 and percentile(xs, 100) == 50.0
    assert mad(xs) == 10.0
    s = robust_stats(xs)
    assert s and s.count == 5 and s.p50 == 30.0
    assert robust_stats([]) is None and median([]) is None


def test_mad_immune_to_single_spike() -> None:
    """Review note: MAD-based regression must not fire on a one-off spike."""
    xs = [300.0] * 29 + [50_000.0]
    s = robust_stats(xs)
    assert s and s.p95 == 300.0  # the single spike never reaches p95


# -- §36/§88 baselines --------------------------------------------------------


def test_baselines_dimensions_and_confidence() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(3))
    baselines = build_baselines(exs)
    svc = [b for b in baselines if b.dimension is BaselineDimension.SERVICE]
    assert svc and svc[0].key == "api" and svc[0].count == 3
    # thin sample -> UNKNOWN confidence, never a firm baseline
    assert svc[0].confidence is Confidence.UNKNOWN
    ops = [b for b in baselines if b.dimension is BaselineDimension.OPERATION]
    assert ops and ops[0].latency is not None and ops[0].latency.p50 == 300.0


def test_baseline_enough_samples_confident() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(10))
    svc = [
        b
        for b in build_baselines(exs)
        if b.dimension is BaselineDimension.SERVICE
    ]
    assert svc[0].confidence is Confidence.MEDIUM


def test_dependency_baseline() -> None:
    exs = tuple(_exec(i, 0, 300.0, fanout=1, callee_dur=120.0)
                for i in range(10))
    deps = [
        b
        for b in build_baselines(exs)
        if b.dimension is BaselineDimension.DEPENDENCY
    ]
    assert deps and deps[0].key == "payments" and deps[0].latency


# -- §37 APIPERF regressions --------------------------------------------------


def _two_windows(base_n=12, cur_n=12, **kw) -> tuple:
    return tuple(
        _exec(i, 0, kw.pop("bdur", 300.0), **kw) for i in range(base_n)
    ) + tuple(
        _exec(100 + i, 1, kw.get("cdur", 300.0), **kw) for i in range(cur_n)
    )


def test_apiperf001_p95_regression() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(12)) + tuple(
        _exec(100 + i, 1, 1200.0) for i in range(12)
    )
    f = [f for f in run_perf_checks(exs) if f.id == "APIPERF001"]
    assert f and "p95" in f[0].description and "1.5x" in f[0].description


def test_apiperf001_single_spike_no_fire() -> None:
    """A single slow request among many does not move p95."""
    cur = [_exec(100 + i, 1, 300.0) for i in range(19)]
    cur.append(_exec(199, 1, 50_000.0))
    exs = tuple(_exec(i, 0, 300.0) for i in range(20)) + tuple(cur)
    assert "APIPERF001" not in _ids(run_perf_checks(exs))


def test_apiperf001_no_regression_when_flat() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(12)) + tuple(
        _exec(100 + i, 1, 310.0) for i in range(12)
    )
    assert "APIPERF001" not in _ids(run_perf_checks(exs))


def test_apiperf001_single_window_no_fire() -> None:
    """One window only -> no baseline comparison exists."""
    exs = tuple(_exec(i, 0, 300.0) for i in range(20))
    assert run_perf_checks(exs) == ()


def test_apiperf002_error_rate() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(12)) + tuple(
        _exec(100 + i, 1, 300.0, status="500" if i < 8 else "200")
        for i in range(12)
    )
    assert "APIPERF002" in _ids(run_perf_checks(exs))


def test_apiperf003_downstream_parent_child() -> None:
    """Downstream attribution comes from recorded call links, not names."""
    exs = tuple(
        _exec(i, 0, 400.0, fanout=1, callee="payments", callee_dur=120.0)
        for i in range(12)
    ) + tuple(
        _exec(100 + i, 1, 1400.0, fanout=1, callee="payments",
              callee_dur=1100.0)
        for i in range(12)
    )
    f = [f for f in run_perf_checks(exs) if f.id == "APIPERF003"]
    assert f and "payments" in f[0].description


def test_apiperf004_retry_amplification() -> None:
    exs = tuple(
        _exec(i, 0, 300.0, retries=0) for i in range(12)
    ) + tuple(
        _exec(100 + i, 1, 300.0, retries=2 if i < 9 else 0)
        for i in range(12)
    )
    f = [f for f in run_perf_checks(exs) if f.id == "APIPERF004"]
    assert f and f[0].confidence is Confidence.LOW and f[0].unknowns


def test_apiperf005_timeout_increase() -> None:
    exs = tuple(
        _exec(i, 0, 300.0, timed_out=False) for i in range(12)
    ) + tuple(
        _exec(100 + i, 1, 300.0, timed_out=i < 8) for i in range(12)
    )
    assert "APIPERF005" in _ids(run_perf_checks(exs))


def test_apiperf006_payload_growth() -> None:
    exs = tuple(
        _exec(i, 0, 300.0, payload=2_000) for i in range(12)
    ) + tuple(
        _exec(100 + i, 1, 300.0, payload=500_000) for i in range(12)
    )
    assert "APIPERF006" in _ids(run_perf_checks(exs))


def test_apiperf007_fanout_increase() -> None:
    exs = tuple(
        _exec(i, 0, 300.0, fanout=1) for i in range(12)
    ) + tuple(
        _exec(100 + i, 1, 300.0, fanout=6) for i in range(12)
    )
    assert "APIPERF007" in _ids(run_perf_checks(exs))


def test_apiperf008_cache_regression() -> None:
    exs = tuple(
        _exec(i, 0, 300.0, cache="HIT") for i in range(12)
    ) + tuple(
        _exec(100 + i, 1, 300.0, cache="MISS" if i < 10 else "HIT")
        for i in range(12)
    )
    assert "APIPERF008" in _ids(run_perf_checks(exs))


def test_perf_determinism() -> None:
    exs = tuple(_exec(i, 0, 300.0, fanout=1) for i in range(12)) + tuple(
        _exec(100 + i, 1, 1200.0, fanout=4) for i in range(12)
    )
    a = [f.to_dict() for f in run_perf_checks(exs)]
    b = [f.to_dict() for f in run_perf_checks(exs)]
    assert a == b


# -- §34-35 critical path -----------------------------------------------------


def test_critical_path_decomposition() -> None:
    ev = Evidence(kind=EvidenceKind.RUNTIME, source="t", summary="s")
    spans = (
        Span(service="api", operation="GET /orders", span_id="r",
             trace_id="t1", duration_ms=1800.0, kind=SpanKind.SERVER,
             evidence=(ev,)),
        Span(service="api", operation="authenticate", span_id="a",
             trace_id="t1", parent_id="r", duration_ms=50.0,
             kind=SpanKind.INTERNAL, evidence=(ev,)),
        Span(service="api", operation="GET charge", span_id="p",
             trace_id="t1", parent_id="r", duration_ms=900.0,
             kind=SpanKind.CLIENT, attributes={"peer.service": "payments"},
             evidence=(ev,)),
        Span(service="api", operation="db query", span_id="d",
             trace_id="t1", parent_id="r", duration_ms=400.0,
             kind=SpanKind.CLIENT, attributes={"peer.service": "pg"},
             evidence=(ev,)),
    )
    cp = critical_path(TraceModel(trace_id="t1", spans=spans,
                                  duration_ms=1800.0, span_count=4))
    labels = {s.label: s.duration_ms for s in cp.segments}
    assert labels["downstream:payments"] == 900.0
    assert labels["downstream:pg"] == 400.0
    assert labels["auth"] == 50.0
    assert labels["service:api"] == 450.0  # 1800 - 1350 attributed children
    assert cp.complete


def test_critical_path_incomplete_unknown() -> None:
    ev = Evidence(kind=EvidenceKind.RUNTIME, source="t", summary="s")
    spans = (
        Span(service="api", operation="op", span_id="x", trace_id="t1",
             parent_id="ghost", duration_ms=10.0, evidence=(ev,)),
    )
    cp = critical_path(
        TraceModel(trace_id="t1", spans=spans, span_count=1, incomplete=True)
    )
    assert not cp.complete and cp.unknowns


# -- §91-93 capacity + cost ---------------------------------------------------


def test_capacity_unknown_dims_honest() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(5))
    sigs = capacity_signals(exs)
    by_dim = {s.dimension.value: s for s in sigs}
    assert by_dim["cpu"].saturation is Saturation.UNKNOWN
    assert by_dim["cpu"].value is None
    assert by_dim["rps"].value is not None


def test_capacity_saturation_thresholds() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(3_700))
    tp = ThresholdProvenance(
        source="org policy p-1", elevated=1.0, saturated=2.0
    )
    from forge_doctor_api.perf.capacity import CapacityDimension

    sigs = capacity_signals(
        exs, thresholds={CapacityDimension.RPS: tp}
    )
    rps = next(s for s in sigs if s.dimension is CapacityDimension.RPS)
    # 3700 requests in one hour-window -> ~1.03 rps -> ELEVATED
    assert rps.saturation is Saturation.ELEVATED
    assert rps.thresholds is tp


def test_cost_drivers() -> None:
    exs = tuple(_exec(i, 0, 300.0, payload=1_000) for i in range(4))
    drivers = {d.driver.value: d.quantity for d in cost_drivers(exs)}
    assert drivers["request_count"] == 4.0
    assert drivers["compute_duration"] == 1_200.0
    assert drivers["network_egress"] == 4_000.0


# -- §148-150 payload ---------------------------------------------------------


def test_payload_shape_static_and_runtime() -> None:
    schema = {
        "type": "object",
        "properties": {f"f{i}": {"type": "string"} for i in range(120)},
    }
    shape = payload_shape_from_schema(schema)
    assert shape.fields == 120 and shape.size is None
    assert is_large(shape) is None  # candidate only, no runtime bytes
    from forge_doctor_api.perf.payload import payload_shape_from_bytes

    assert is_large(payload_shape_from_bytes(600_000)) is True
    assert is_large(payload_shape_from_bytes(1_000)) is False


# -- §154-155 latency budget --------------------------------------------------


def test_budget_evaluation() -> None:
    ev = Evidence(kind=EvidenceKind.RUNTIME, source="t", summary="s")
    spans = (
        Span(service="api", operation="op", span_id="r", trace_id="t1",
             duration_ms=1_000.0, kind=SpanKind.SERVER, evidence=(ev,)),
        Span(service="api", operation="pay", span_id="p", trace_id="t1",
             parent_id="r", duration_ms=900.0, kind=SpanKind.CLIENT,
             attributes={"peer.service": "payments"}, evidence=(ev,)),
    )
    cp = critical_path(
        TraceModel(trace_id="t1", spans=spans, duration_ms=1_000.0,
                   span_count=2)
    )
    budget = ApiLatencyBudget(
        name="checkout",
        hops=(BudgetHop(name="payments", budget_ms=500.0),
              BudgetHop(name="api", budget_ms=2_000.0)),
    )
    report = evaluate_budget(cp, budget)
    by_hop = {h.hop: h for h in report.hops}
    assert by_hop["payments"].over_budget is True
    assert by_hop["api"].over_budget is False
    assert report.within_budget is False


def test_budget_missing_hop_unknown() -> None:
    ev = Evidence(kind=EvidenceKind.RUNTIME, source="t", summary="s")
    cp = critical_path(
        TraceModel(
            trace_id="t1",
            spans=(
                Span(service="api", operation="op", span_id="r",
                     trace_id="t1", duration_ms=10.0,
                     kind=SpanKind.SERVER, evidence=(ev,)),
            ),
            duration_ms=10.0, span_count=1,
        )
    )
    budget = ApiLatencyBudget(
        name="b", hops=(BudgetHop(name="payments", budget_ms=100.0),)
    )
    report = evaluate_budget(cp, budget)
    assert report.hops[0].over_budget is None and report.unknowns


# -- §96-97/§169 experiments ---------------------------------------------------


def _experiment(**kw) -> Experiment:
    return Experiment(
        name=kw.pop("name", "exp"),
        scenario=RequestScenario(
            route="/checkout",
            expected_constraints=kw.pop("constraints", ()),
        ),
        baseline=kw.pop("baseline", None) or robust_stats(
            [300.0] * 20
        ),
        **kw,
    )


def test_experiment_supported() -> None:
    e = _experiment(
        adjustments={"p95": 0.8},
        constraints=(Constraint(metric="p95", op="<=", value=500.0),),
    )
    r = evaluate_experiment(e)
    assert r.verdict is ExperimentVerdict.SUPPORTED
    assert r.projected["p95"] == 300.0 * 0.8


def test_experiment_constraint_violated_lists_them() -> None:
    e = _experiment(
        adjustments={"p95": 2.0},
        constraints=(
            Constraint(metric="p95", op="<=", value=400.0),
            Constraint(metric="p50", op="<=", value=1_000.0),
        ),
    )
    r = evaluate_experiment(e)
    assert r.verdict is ExperimentVerdict.CONSTRAINT_VIOLATED
    assert len(r.violated_constraints) == 1
    assert r.violated_constraints[0].metric == "p95"


def test_experiment_not_supported_hypothesis() -> None:
    e = _experiment(
        adjustments={"p95": 1.1},
        hypothesis=Constraint(metric="p95", op="<", value=290.0),
    )
    assert evaluate_experiment(e).verdict is ExperimentVerdict.NOT_SUPPORTED


def test_experiment_inconclusive_no_baseline() -> None:
    e = Experiment(
        name="no-base",
        scenario=RequestScenario(route="/x"),
        baseline=None,
    )
    r = evaluate_experiment(e)
    assert r.verdict is ExperimentVerdict.INCONCLUSIVE and r.unknowns


# -- §38/§90 correlation ------------------------------------------------------


def test_correlation_requires_entity_overlap() -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(12)) + tuple(
        _exec(100 + i, 1, 1200.0) for i in range(12)
    )
    regs = run_perf_checks(exs)
    change = ChangeEvent(
        change_id="c1", subject="api:/checkout", kind="schema grew",
        entities=("api:/checkout",),
    )
    corrs = correlate_changes((change,), regs)
    assert corrs and "correlat" in corrs[0].caveat
    assert corrs[0].confidence is Confidence.LOW
    unrelated = ChangeEvent(
        change_id="c2", subject="other", kind="rename",
        entities=("other:svc",),
    )
    assert correlate_changes((unrelated,), regs) == ()


# -- §33 observed signals ------------------------------------------------------


def test_observed_signals_only_with_evidence() -> None:
    sigs = performance_signals(
        (_exec(1, 0, 300.0, retries=3, fanout=5),)
    )
    fams = {s.family for s in sigs}
    assert PerformanceFamily.RETRY_AMPLIFICATION in fams
    assert PerformanceFamily.FANOUT_AMPLIFICATION in fams
    # no cache/payload/queueing evidence -> no such signals
    assert PerformanceFamily.QUEUEING not in fams
    assert PerformanceFamily.SERIALIZATION_OVERHEAD not in fams


# -- §162 CLI -------------------------------------------------------------------


def _write_otlp(root: Path, n: int, w: int, dur: float) -> None:
    spans = [
        {
            "traceId": f"t{i}", "spanId": f"s{i}", "name": "GET /c",
            "kind": 2, "startTimeUnixNano": str(BASE + w * HOUR + i * 1_000),
            "endTimeUnixNano": str(BASE + w * HOUR + i * 1_000 + int(dur * 1e6)),
            "attributes": [
                {"key": "http.route", "value": {"stringValue": "/c"}},
            ],
            "status": {"code": 1},
        }
        for i in range(n)
    ]
    import json

    (root / f"t{w}.json").write_text(
        json.dumps(
            {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": [
                                {
                                    "key": "service.name",
                                    "value": {"stringValue": "api"},
                                }
                            ]
                        },
                        "scopeSpans": [{"scope": {}, "spans": spans}],
                    }
                ]
            }
        )
    )


def test_runtime_cli(tmp_path: Path) -> None:
    _write_otlp(tmp_path, 12, 0, 300.0)
    _write_otlp(tmp_path, 12, 1, 1200.0)
    runner = CliRunner()
    r = runner.invoke(app, ["runtime", "requests", str(tmp_path)])
    assert r.exit_code == 0 and "request execution" in r.stdout
    r = runner.invoke(app, ["runtime", "baseline", str(tmp_path)])
    assert r.exit_code == 0 and "api" in r.stdout
    r = runner.invoke(app, ["runtime", "regressions", str(tmp_path)])
    assert r.exit_code == 0 and "APIPERF001" in r.stdout


def test_runtime_cli_regressions_empty(tmp_path: Path) -> None:
    _write_otlp(tmp_path, 12, 0, 300.0)
    runner = CliRunner()
    r = runner.invoke(app, ["runtime", "regressions", str(tmp_path)])
    assert r.exit_code == 0 and "no regressions" in r.stdout
