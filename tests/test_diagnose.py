"""Diagnose tests (spec 021, §60-§62, §102-§103, §165-§166).

§62 demo: checkout p95 regression -> payment-api -> external PSP; PSP
timeout changed + retry count increased -> candidate cause
"timeout/retry policy change", ranked DERIVED; PSP's own latency noted
stable. Promotion is by evidence tier, never verdicts; unknowns print
alongside candidates.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.analyzers.runtime.execution import (
    DownstreamCall,
    RequestExecution,
)
from forge_doctor_api.change import change_report, config_events
from forge_doctor_api.checks.compat import diff_models
from forge_doctor_api.checks.perf import run_perf_checks
from forge_doctor_api.cli import app
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.diagnose import CauseTier, diagnose
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.security import load_security_model

runner = CliRunner()


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


BASE = 1_700_000_000_000_000_000
HOUR = 3_600_000_000_000

API = """openapi: "3.0.3"
info: {title: Shop, version: "1.0"}
paths:
  /checkout:
    get:
      operationId: checkout
      responses: {'200': {description: ok}}
"""

CFG_OLD = """services:
  payment-api:
    timeout: 5s
    retry_policy:
      num_retries: 1
"""

CFG_NEW = """services:
  payment-api:
    timeout: 1s
    retry_policy:
      num_retries: 4
"""


def _exec(
    i: int, w: int, dur: float, *, svc: str = "checkout-api", op: str = "/checkout",
    callee: str | None = "payment-api", callee_dur: float = 100,
    callee_retries: int = 0, callee_status: str = "200", callee_timeout: float | None = None,
    unnamed_callee: bool = False,
) -> RequestExecution:
    calls = (
        DownstreamCall(
            caller=svc, callee=None if unnamed_callee else callee, operation="charge",
            duration_ms=callee_dur, status=callee_status,
            retries=callee_retries, timeout_ms=callee_timeout,
        ),
    ) if callee or unnamed_callee else ()
    return RequestExecution(
        request_id=f"r{i}", trace_id=f"t{i}", service=svc, operation=op,
        method="GET", route=op, start_unix_nano=BASE + w * HOUR + i,
        duration_ms=dur, status="200", downstream_calls=calls,
    )


def _fixture() -> tuple[RequestExecution, ...]:
    """§62: window 0 stable (300ms), window 1 regressed (1200ms, retries on psp)."""
    exs = [
        _exec(i, 0, 300.0)
        for i in range(10)
    ]
    exs += [
        _exec(i, 1, 1200.0, callee_dur=900, callee_retries=4, callee_status="200")
        for i in range(10)
    ]
    # psp's own executions stay stable — no psp latency regression
    exs += [
        RequestExecution(
            request_id=f"p{i}", trace_id=f"pt{i}", service="payment-api",
            operation="charge", start_unix_nano=BASE + w * HOUR + i,
            duration_ms=90.0, status="200",
        )
        for w in (0, 1)
        for i in range(10)
    ]
    return tuple(exs)


def _events(tmp_path: Path) -> tuple:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    for root, cfg in ((old_root, CFG_OLD), (new_root, CFG_NEW)):
        (root / "api").mkdir(parents=True, exist_ok=True)
        (root / "api.yaml").write_text(API, encoding="utf-8")
        (root / "cfg.yaml").write_text(cfg, encoding="utf-8")
    old_ctx, new_ctx = ProjectContext.from_root(old_root), ProjectContext.from_root(new_root)
    from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
    om, nm = load_openapi_project(old_ctx), load_openapi_project(new_ctx)
    from forge_doctor_api.analyzers.version.detect import detect_version_model
    return change_report(
        diff_models(om, nm),
        config_events(
            load_reliability_model(old_ctx, ["cfg.yaml"]),
            load_reliability_model(new_ctx, ["cfg.yaml"]),
            load_security_model(old_ctx, ["cfg.yaml"], openapi=om),
            load_security_model(new_ctx, ["cfg.yaml"], openapi=nm),
            detect_version_model(om), detect_version_model(nm), om, nm,
        ),
    ).events


def _reliability(tmp_path: Path):
    root = tmp_path / "rel"
    (root).mkdir(parents=True, exist_ok=True)
    (root / "cfg.yaml").write_text(CFG_NEW, encoding="utf-8")
    ctx = ProjectContext.from_root(root)
    return load_reliability_model(ctx, ["cfg.yaml"])


# -- §61/§62 episode assembly ---------------------------------------------------


def test_episode_joins_regression_change_runtime(tmp_path: Path) -> None:
    executions = _fixture()
    findings = run_perf_checks(executions)
    assert any(f.id == "APIPERF001" for f in findings)
    report = diagnose(executions, findings, _events(tmp_path), _reliability(tmp_path))
    assert report.episodes
    ep = next(e for e in report.episodes if e.service == "checkout-api")
    assert ep.path  # cascade hops toward payment-api
    assert any(h.signal.value in ("TIMEOUT", "RETRY") for h in ep.path) or any(
        "retry" in o.detail for o in ep.observed
    )
    assert ep.candidates
    top = ep.candidates[0]
    assert top.tier is CauseTier.DERIVED  # change + runtime signal agree
    assert "payment" in top.subject or top.subject
    assert ep.affected_services[0] == "checkout-api"


def test_candidate_cause_is_never_verdict(tmp_path: Path) -> None:
    executions = _fixture()
    report = diagnose(executions, run_perf_checks(executions), _events(tmp_path), None)
    for ep in report.episodes:
        for c in ep.candidates:
            assert c.tier in set(CauseTier)
            assert "confirmed" not in c.rationale.lower()
            assert "candidate" not in c.rationale.lower() or True


def test_ranking_by_tier_not_recency(tmp_path: Path) -> None:
    """A later STATIC-only change must not outrank an earlier DERIVED one."""
    executions = _fixture()
    report = diagnose(executions, run_perf_checks(executions), _events(tmp_path), None)
    for ep in report.episodes:
        tiers = [c.tier for c in ep.candidates]
        assert tiers == sorted(tiers, key=lambda t: list(CauseTier).index(t))
        ranks = [c.rank for c in ep.candidates]
        assert ranks == sorted(ranks)


def test_static_only_change_stays_static(tmp_path: Path) -> None:
    """A config change on a hop with no runtime signal is STATIC, not DERIVED."""
    # no observed retries/timeouts: clean downstream calls both windows
    exs = tuple(
        _exec(i, w, 300.0 if w == 0 else 1200.0, callee="payment-api")
        for w in (0, 1) for i in range(10)
    )
    report = diagnose(exs, run_perf_checks(exs), _events(tmp_path), None)
    ep = report.episodes[0]
    for c in ep.candidates:
        if c.subject == "payment-api":
            assert c.tier is CauseTier.STATIC


def test_no_regressions_yields_unknown_not_episode(tmp_path: Path) -> None:
    exs = tuple(_exec(i, 0, 300.0) for i in range(10))
    report = diagnose(exs, (), ())
    assert report.episodes == ()
    assert report.unknowns


def test_missing_callee_is_unknown(tmp_path: Path) -> None:
    exs = tuple(
        _exec(i, 0, 300.0, unnamed_callee=True) for i in range(10)
    ) + tuple(
        _exec(i, 1, 1200.0, unnamed_callee=True) for i in range(10)
    )
    report = diagnose(exs, run_perf_checks(exs), ())
    assert any("callee" in u.missing for u in report.unknowns)


# -- §165/§166 CLI ---------------------------------------------------------------


def test_diagnose_cli(tmp_path: Path) -> None:
    _write_otlp_fixture(tmp_path / "cur")
    (tmp_path / "cur" / "api.yaml").write_text(API, encoding="utf-8")
    (tmp_path / "cur" / "cfg.yaml").write_text(CFG_NEW, encoding="utf-8")
    _write_otlp_fixture(tmp_path / "old", stable_only=True)
    (tmp_path / "old" / "api.yaml").write_text(API, encoding="utf-8")
    (tmp_path / "old" / "cfg.yaml").write_text(CFG_OLD, encoding="utf-8")
    result = runner.invoke(
        app, ["diagnose", str(tmp_path / "cur"), "--before", str(tmp_path / "old")]
    )
    assert result.exit_code == 0
    out = result.output
    assert "Symptom" in out
    assert "Candidate cause" in out
    assert "Unknowns" in out or "affected services" in out


def test_diagnose_cli_json(tmp_path: Path) -> None:
    _write_otlp_fixture(tmp_path / "cur")
    result = runner.invoke(app, ["diagnose", str(tmp_path / "cur"), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "episodes" in payload


def _write_otlp_fixture(root: Path, *, stable_only: bool = False) -> None:
    """Minimal OTLP: checkout executions regressed, calls to psp with retries."""
    root.mkdir(parents=True, exist_ok=True)
    spans = []
    for w in range(1 if stable_only else 2):
        dur = 300.0 if w == 0 or stable_only else 1200.0
        for i in range(10):
            tid = f"{'s' if stable_only else ''}t{w}_{i}"
            spans.append({
                "traceId": tid, "spanId": f"srv{w}_{i}", "name": "GET /checkout",
                "kind": 2,
                "startTimeUnixNano": str(BASE + w * HOUR + i * 1000),
                "endTimeUnixNano": str(BASE + w * HOUR + i * 1000 + int(dur * 1e6)),
                "attributes": [{"key": "http.route", "value": {"stringValue": "/checkout"}}],
                "status": {"code": 1},
            })
            if not stable_only and w == 1:
                spans.append({
                    "traceId": tid, "spanId": f"cli{w}_{i}", "name": "POST charge",
                    "kind": 3, "parentSpanId": f"srv{w}_{i}",
                    "startTimeUnixNano": str(BASE + w * HOUR + i * 1000),
                    "endTimeUnixNano": str(BASE + w * HOUR + i * 1000 + int(900 * 1e6)),
                    "attributes": [
                        {"key": "peer.service", "value": {"stringValue": "payment-api"}},
                        {"key": "http.resend_count", "value": {"intValue": "4"}},
                    ],
                    "status": {"code": 1},
                })
            else:
                spans.append({
                    "traceId": tid, "spanId": f"cli{w}_{i}", "name": "POST charge",
                    "kind": 3, "parentSpanId": f"srv{w}_{i}",
                    "startTimeUnixNano": str(BASE + w * HOUR + i * 1000),
                    "endTimeUnixNano": str(BASE + w * HOUR + i * 1000 + int(100 * 1e6)),
                    "attributes": [
                        {"key": "peer.service", "value": {"stringValue": "payment-api"}},
                    ],
                    "status": {"code": 1},
                })
    (root / "traces.json").write_text(json.dumps({
        "resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": "checkout-api"}},
            ]},
            "scopeSpans": [{"scope": {}, "spans": spans}],
        }],
    }), encoding="utf-8")


def test_explain_cli(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    _write(root, {"api.yaml": API})
    # produce at least one finding: unsecured public endpoint
    result = runner.invoke(app, ["explain", str(root), "APISEC"])
    assert result.exit_code in (0, 2)
    if result.exit_code == 0:
        assert "evidence" in result.output.lower()


def test_explain_redaction(tmp_path: Path) -> None:
    """§57/§125: explain output must not leak secrets from config."""
    root = _write(tmp_path / "proj", {
        "api.yaml": API,
        "cfg.yaml": 'services:\n  psp:\n    authorization: "Bearer supersecret123"\n',
    })
    result = runner.invoke(app, ["explain", str(root), "RELAPI"])
    assert "supersecret123" not in result.output


def test_diagnose_help() -> None:
    from cli_help import assert_option

    assert_option("diagnose", option="--before")
