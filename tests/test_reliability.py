"""Reliability intelligence tests (spec 017, §39-47, §156-158, §228)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.analyzers.runtime import RequestExecution
from forge_doctor_api.checks.relapi import run_reliability_checks
from forge_doctor_api.checks.relapi.engine import run_depth_checks
from forge_doctor_api.cli import app
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.reliability import (
    BudgetVerdict,
    IdempotencyVerdict,
    LoadBalancingKind,
    RetryPolicy,
    aggregate_idempotency,
    amplification,
    error_budget,
    evaluate_timeout_budget,
    load_reliability_model,
)
from forge_doctor_api.reliability.model import (
    ApiReliabilityModel,
    ApiServiceObjective,
    IdempotencySource,
    TimeoutConfig,
)

BASE = 1_700_000_000_000_000_000


def _ctx(tmp_path: Path, files: dict[str, str]) -> ProjectContext:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return ProjectContext.from_root(tmp_path)


def _load(tmp_path: Path, files: dict[str, str]):
    ctx = _ctx(tmp_path, files)
    return load_reliability_model(ctx, list(ctx.iter_files()))


# ---------- retry policy extraction ----------


def test_retry_policy_generic_yaml(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "app.yaml": "retries:\n  scope: gateway\n  max_attempts: 3\n",
    })
    assert len(m.retry_policies) == 1
    assert m.retry_policies[0].scope == "gateway"
    assert m.retry_policies[0].max_attempts == 3
    assert m.retry_policies[0].evidence[0].source == "app.yaml"


def test_retry_policy_envoy_shape(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "envoy.yaml": (
            "route_config:\n"
            "  name: payments\n"
            "  retry_policy:\n"
            "    num_retries: 4\n"
            "    retry_on: 5xx,reset\n"
        ),
    })
    pol = next(p for p in m.retry_policies if p.scope == "payments")
    assert pol.max_attempts == 4
    assert set(pol.retryable_statuses) == {"5xx", "reset"}


def test_no_fabricated_policies_on_plain_yaml(tmp_path: Path) -> None:
    m = _load(tmp_path, {"readme.yaml": "title: nothing\nnotes: text\n"})
    assert not m.retry_policies
    assert not m.timeouts


def test_retries_without_grpc_markers_not_double_counted(
    tmp_path: Path,
) -> None:
    m = _load(tmp_path, {
        "app.yaml": "retries:\n  scope: gw\n  max_attempts: 2\n"
                    "timeouts:\n  scope: gw\n  timeout: 5000\n",
    })
    assert len(m.retry_policies) == 1
    assert {t.scope for t in m.timeouts} == {"gw"}


def test_grpc_service_config_extracted(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "grpc-svc.json": (
            '{"methodConfig": [{"name": [{"service": "pkg.Svc"}],'
            ' "retryPolicy": {"maxAttempts": 3}}],'
            ' "loadBalancingConfig": [{"pick_first": {}}],'
            ' "healthCheck": {"serviceName": "pkg.Svc"},'
            ' "waitForReady": true}'
        ),
    })
    assert any(p.max_attempts == 3 for p in m.retry_policies)
    assert any(h.protocol == "grpc-health-v1" for h in m.health_checks)
    assert any(lb.kind is not LoadBalancingKind.UNKNOWN
               or lb.scope for lb in m.load_balancing)


# ---------- amplification ----------


def _pol(scope: str, n: int, statuses: tuple[str, ...] = ()) -> RetryPolicy:
    return RetryPolicy(scope=scope, max_attempts=n, retryable_statuses=statuses)


def test_amplification_explicit_all_hops() -> None:
    amp = amplification(
        ("gateway", "service"), (_pol("gateway", 3), _pol("service", 3))
    )
    assert amp.complete
    assert amp.potential_attempts == 9


def test_amplification_edge_scope_binds_caller() -> None:
    amp = amplification(
        ("gateway", "service"),
        (_pol("gateway->service", 3), _pol("service", 2)),
    )
    assert amp.complete
    assert amp.potential_attempts == 6


def test_amplification_missing_hop_is_unknown() -> None:
    amp = amplification(("a", "b"), (_pol("a", 3),))
    assert not amp.complete
    assert amp.potential_attempts is None
    assert amp.missing == ("b",)
    assert amp.unknowns
    assert "explicit per-hop" in amp.unknowns[0].resolution


def test_amplification_no_default_assumed_for_attempts() -> None:
    amp = amplification(("a",), (RetryPolicy(scope="a"),))
    assert not amp.complete  # max_attempts=None -> missing


def test_retryable_overlap_only_when_declared() -> None:
    # One policy silent on statuses -> no overlap claim
    amp = amplification(
        ("a", "b"), (_pol("a", 2, ("5xx",)), _pol("b", 2))
    )
    assert amp.retryable_overlap == ()
    # Both declare -> intersection reported
    amp2 = amplification(
        ("a", "b"),
        (_pol("a", 2, ("5xx", "reset")), _pol("b", 2, ("5xx",))),
    )
    assert amp2.retryable_overlap == ("5xx",)


# ---------- idempotency ----------


def test_idempotency_method_alone_never_decides() -> None:
    for method in ("GET", "PUT", "POST", "DELETE"):
        ev = aggregate_idempotency(
            f"{method} /x",
            (IdempotencySource(kind="http_method", detail=method),),
        )
        assert ev.verdict is IdempotencyVerdict.UNKNOWN
        assert ev.unknowns


def test_idempotency_key_asserts() -> None:
    ev = aggregate_idempotency(
        "POST /pay",
        (
            IdempotencySource(kind="http_method", detail="POST"),
            IdempotencySource(
                kind="idempotency_key", detail="Idempotency-Key",
                supports=True,
            ),
        ),
    )
    assert ev.verdict is IdempotencyVerdict.IDEMPOTENT


def test_idempotency_negative_assertion_wins() -> None:
    ev = aggregate_idempotency(
        "POST /pay",
        (
            IdempotencySource(
                kind="idempotency_key", detail="k", supports=True),
            IdempotencySource(
                kind="handler_semantics", detail="double-charge",
                supports=False),
        ),
    )
    assert ev.verdict is IdempotencyVerdict.NON_IDEMPOTENT


def test_idempotency_config_block_extracted(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "ops.yaml": (
            "idempotency:\n"
            "  subject: 'POST /payments'\n"
            "  method: POST\n"
        ),
    })
    assert len(m.idempotency) == 1
    assert m.idempotency[0].subject == "POST /payments"
    assert m.idempotency[0].verdict is IdempotencyVerdict.UNKNOWN
    assert m.idempotency[0].sources[0].kind == "http_method"


# ---------- timeout budgets ----------


def test_budget_impossible_parallel() -> None:
    # 2000ms downstream exceeds the 1000ms caller budget even in parallel
    b = evaluate_timeout_budget(
        "gw", 1000.0, (("a", 2000.0), ("b", 900.0))
    )
    assert b.verdict is BudgetVerdict.IMPOSSIBLE
    assert b.parallel_need_ms == 2000.0


def test_budget_at_risk_sequential_only() -> None:
    b = evaluate_timeout_budget(
        "gw", 1000.0, (("a", 600.0), ("b", 600.0))
    )
    assert b.verdict is BudgetVerdict.AT_RISK
    assert b.sequential_need_ms == 1200.0
    assert b.parallel_need_ms == 600.0


def test_budget_feasible() -> None:
    b = evaluate_timeout_budget(
        "gw", 5000.0, (("a", 600.0), ("b", 600.0))
    )
    assert b.verdict is BudgetVerdict.FEASIBLE


def test_budget_unknown_without_caller_timeout() -> None:
    b = evaluate_timeout_budget("gw", None, (("a", 600.0),))
    assert b.verdict is BudgetVerdict.UNKNOWN
    assert any("caller" in u.missing for u in b.unknowns)


def test_budget_unknown_downstream_budget_flags_risk() -> None:
    b = evaluate_timeout_budget("gw", 5000.0, (("a", 600.0), ("b", None)))
    assert b.verdict is BudgetVerdict.AT_RISK
    assert any("b" in u.subject for u in b.unknowns)


# ---------- config: cb / health / lb / shutdown ----------


def test_circuit_breaker_resilience4j(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "res.yaml": (
            "resilience4j:\n"
            "  circuitbreaker:\n"
            "    instances:\n"
            "      payments:\n"
            "        failureRateThreshold: 50\n"
        ),
    })
    assert m.circuit_breakers
    assert any(cb.provider == "resilience4j" for cb in m.circuit_breakers)


def test_circuit_breaker_envoy_outlier(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "envoy.yaml": "clusters:\n  name: svc\n"
                      "  outlier_detection:\n    consecutive_5xx: 3\n",
    })
    assert m.circuit_breakers


def test_health_endpoint_only_when_explicit(tmp_path: Path) -> None:
    # A service existing in config must NOT imply a health endpoint.
    m = _load(tmp_path, {"app.yaml": "name: svc\nport: 8080\n"})
    assert not m.health_checks


def test_http_health_endpoint_explicit(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "deploy.yaml": (
            "service: api\n"
            "health_check:\n  path: /healthz\n"
        ),
    })
    assert m.health_checks


def test_load_balancing_extracted(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "envoy.yaml": "cluster:\n  name: svc\n  lb_policy: round_robin\n",
    })
    assert m.load_balancing
    assert m.load_balancing[0].kind is LoadBalancingKind.ROUND_ROBIN


def test_graceful_shutdown_extracted(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "deploy.yaml": "name: svc\ngraceful_shutdown: 30s\n",
    })
    assert m.shutdown_evidence
    assert m.shutdown_evidence[0].drain_seconds == 30000.0


# ---------- SLO / error budget ----------


def _exec(status: str = "ok", start: int = BASE) -> RequestExecution:
    return RequestExecution(
        request_id="r", trace_id="t", service="api", operation="op",
        start_unix_nano=start, status=status,
    )


def test_slo_extracted_from_config(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "slo.yaml": (
            "slo:\n  name: api-availability\n  metric: availability\n"
            "  target: 99.9\n  window: '2023-11-14T22'\n"
        ),
    })
    assert m.objectives
    assert abs(m.objectives[0].target - 0.999) < 1e-9


def test_error_budget_sufficient_window() -> None:
    obj = ApiServiceObjective(
        name="avail", metric="availability", target=0.9,
        window="2023-11-14T22",
    )
    execs = tuple(_exec("error" if i == 0 else "ok") for i in range(10))
    b = error_budget(obj, execs)
    assert b.sufficient
    assert b.total == 10
    assert b.consumed == 1.0
    assert abs(b.remaining) < 1e-9  # 10% of 10 = 1 allowed


def test_error_budget_insufficient_window_guard() -> None:
    obj = ApiServiceObjective(
        name="avail", metric="availability", target=0.999,
        window="2023-11-14T22",
    )
    b = error_budget(obj, (_exec(), _exec(), _exec()))
    assert not b.sufficient
    assert b.unknowns


def test_error_budget_window_filters() -> None:
    obj = ApiServiceObjective(
        name="avail", metric="availability", target=0.5,
        window="2023-11-14T23",
    )
    execs = tuple(
        _exec(start=BASE + i * 3_600_000_000_000) for i in range(10)
    )
    b = error_budget(obj, execs)
    assert b.total == 1
    assert not b.sufficient


# ---------- RELAPI engine ----------


def test_relapi001_fires_on_stacked_policies(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "retries:\n  scope: gw\n  max_attempts: 3\n",
        "b.yaml": "retries:\n  scope: svc\n  max_attempts: 3\n",
    })
    ids = [f.id for f in run_reliability_checks(m, hops=("gw", "svc"))]
    assert "RELAPI001" in ids


def test_relapi001_unknown_when_policy_missing(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "retries:\n  scope: gw\n  max_attempts: 3\n",
    })
    findings = run_reliability_checks(m, hops=("gw", "svc"))
    amp = [f for f in findings if f.id == "RELAPI001"]
    assert amp
    assert "unknown" in amp[0].description
    assert amp[0].unknowns


def test_relapi002_manual_review_for_retried_scope(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "retries:\n  scope: gw\n  max_attempts: 2\n",
    })
    f = [f for f in run_reliability_checks(m) if f.id == "RELAPI002"]
    assert f
    assert "manual review" in f[0].description


def test_relapi002_silent_when_idempotent(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": (
            "retries:\n  scope: gw\n  max_attempts: 2\n"
            "idempotency:\n  subject: gw\n"
            "  key_header: Idempotency-Key\n"
        ),
    })
    f = [f for f in run_reliability_checks(m) if f.id == "RELAPI002"]
    assert not f


def test_relapi003_impossible_budget(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": (
            "timeouts:\n  scope: gw\n  timeout: 1000\n"
            "downstream:\n  scope: dep\n  timeout: 2000\n"
        ),
    })
    findings = run_reliability_checks(m, hops=("gw", "dep"))
    f = [f for f in findings if f.id == "RELAPI003"]
    assert f
    assert "exceed" in f[0].description


def test_relapi003_silent_without_hops(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "timeouts:\n  scope: gw\n  timeout: 1000\n",
    })
    assert not [f for f in run_reliability_checks(m)
                if f.id == "RELAPI003"]


def test_relapi004_gap_when_no_callsite_deadline(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "timeouts:\n  scope: gw\n  timeout: 1000\n",
    })
    assert any(f.id == "RELAPI004" for f in run_reliability_checks(m))


def test_relapi005_candidate_without_cb(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "retries:\n  scope: gw\n  max_attempts: 2\n",
    })
    assert any(f.id == "RELAPI005" for f in run_reliability_checks(m))


def test_relapi005_silent_with_cb(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "retries:\n  scope: gw\n  max_attempts: 2\n"
                  "resilience4j:\n  circuitbreaker:\n"
                  "    instances:\n      gw:\n        slidingWindowSize: 5\n",
    })
    assert not [f for f in run_reliability_checks(m)
                if f.id == "RELAPI005"]


def test_relapi006_007_candidates(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "a.yaml": "timeouts:\n  scope: gw\n  timeout: 1000\n",
    })
    ids = {f.id for f in run_reliability_checks(m)}
    assert {"RELAPI006", "RELAPI007"} <= ids


def test_empty_model_no_findings(tmp_path: Path) -> None:
    m = _load(tmp_path, {"x.yaml": "nothing: here\n"})
    assert run_reliability_checks(m) == ()


# ---------- §228 demo ----------


def test_demo_228(tmp_path: Path) -> None:
    m = _load(tmp_path, {
        "gw.yaml": (
            "retries:\n  scope: gateway->payment-service\n"
            "  max_attempts: 3\n"
        ),
        "svc.yaml": (
            "retries:\n  scope: payment-service\n  max_attempts: 3\n"
            "idempotency:\n  subject: 'POST /payments'\n  method: POST\n"
        ),
    })
    findings = run_reliability_checks(m, hops=("gateway", "payment-service"))
    ids = {f.id for f in findings}
    assert "RELAPI001" in ids
    amp = next(f for f in findings if f.id == "RELAPI001")
    assert "9" in amp.description
    idem = [f for f in findings if f.id == "RELAPI002"]
    assert idem and all("manual review" in f.description for f in idem)
    assert m.idempotency[0].verdict is IdempotencyVerdict.UNKNOWN


# ---------- CLI ----------


def test_reliability_inspect_cli(tmp_path: Path) -> None:
    _ctx(tmp_path, {"a.yaml": "retries:\n  scope: gw\n  max_attempts: 2\n"})
    r = CliRunner().invoke(app, ["reliability", "inspect", str(tmp_path)])
    assert r.exit_code == 0
    assert "retry policies: 1" in r.output


def test_reliability_path_cli(tmp_path: Path) -> None:
    _ctx(tmp_path, {
        "a.yaml": "retries:\n  scope: gw\n  max_attempts: 3\n",
        "b.yaml": "retries:\n  scope: svc\n  max_attempts: 3\n",
    })
    r = CliRunner().invoke(
        app,
        ["reliability", "path", str(tmp_path), "--hop", "gw",
         "--hop", "svc"],
    )
    assert r.exit_code == 0
    assert "RELAPI001" in r.output


def test_reliability_path_inline_policies(tmp_path: Path) -> None:
    _ctx(tmp_path, {})
    r = CliRunner().invoke(
        app,
        ["reliability", "path", str(tmp_path), "--hop", "a", "--hop", "b",
         "--policy", "a=3", "--policy", "b=3", "--json"],
    )
    assert r.exit_code == 0
    import json
    payload = json.loads(r.output)
    ids = [f["id"] for f in payload["findings"]]
    assert "RELAPI001" in ids
    amp = next(f for f in payload["findings"] if f["id"] == "RELAPI001")
    assert "9" in amp["description"]


def test_reliability_path_requires_hops(tmp_path: Path) -> None:
    _ctx(tmp_path, {})
    r = CliRunner().invoke(app, ["reliability", "path", str(tmp_path)])
    assert r.exit_code == 2


def test_reliability_determinism(tmp_path: Path) -> None:
    files = {
        "b.yaml": "retries:\n  scope: b\n  max_attempts: 2\n",
        "a.yaml": "retries:\n  scope: a\n  max_attempts: 2\n",
    }
    m1 = _load(tmp_path / "r1", files)
    m2 = _load(tmp_path / "r2", files)
    f1 = [f.description for f in run_reliability_checks(m1)]
    f2 = [f.description for f in run_reliability_checks(m2)]
    assert f1 == f2


# -- spec 062: depth checks over evidenced edges ------------------------------


def _depth_model() -> ApiReliabilityModel:
    return ApiReliabilityModel(
        retry_policies=(
            RetryPolicy(scope="gw", max_attempts=3),
            RetryPolicy(scope="svc", max_attempts=2),
        ),
        timeouts=(
            TimeoutConfig(scope="gw", timeout_ms=100.0),
            TimeoutConfig(scope="svc", timeout_ms=500.0),
        ))


def test_depth_retry_amplification() -> None:
    findings = run_depth_checks(_depth_model(), (("gw", "svc"),))
    amp = [f for f in findings if f.id == "APIREL001"]
    assert amp and "6" in amp[0].description  # 3 * 2 bound


def test_depth_timeout_cascade() -> None:
    findings = run_depth_checks(_depth_model(), (("gw", "svc"),))
    assert any(f.id == "APIREL002" and "100.0ms < callee timeout 500.0ms"
               in f.description for f in findings)


def test_depth_unknown_callee_timeout() -> None:
    findings = run_depth_checks(_depth_model(), (("gw", "other"),))
    f = next((f for f in findings if f.id == "APIREL002"), None)
    assert f is not None and f.unknowns


def test_depth_no_evidence_no_findings() -> None:
    # no declared edges -> nothing; name similarity impossible
    assert run_depth_checks(_depth_model(), ()) == ()
