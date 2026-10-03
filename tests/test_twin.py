"""API Digital Twin tests (spec 019, §63-64, §113, §172)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.analyzers.runtime import RequestExecution
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.reliability.model import ApiServiceObjective
from forge_doctor_api.security import load_security_model
from forge_doctor_api.twin import (
    ApiTwinHistory,
    TwinDriftKind,
    TwinSnapshot,
    TwinState,
    assemble_twin,
    twin_drift,
)

HEADER = "openapi: 3.0.3\ninfo: {title: T, version: '1.2.0'}\n"
BASE = 1_700_000_000_000_000_000


def _project(tmp_path: Path, files: dict[str, str]) -> ProjectContext:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return ProjectContext.from_root(tmp_path)


def _exec(op: str, service: str = "api", status: str = "ok",
          route: str | None = None,
          start: int = BASE) -> RequestExecution:
    return RequestExecution(
        request_id=f"r{op}", trace_id="t", service=service,
        operation=op, route=route, start_unix_nano=start, status=status,
    )


# ---------- assembly ----------


def test_twin_five_states_present_and_absent(tmp_path: Path) -> None:
    ctx = _project(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"
        ),
        "app.py": (
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/a')\ndef a():\n    pass\n"
        ),
    })
    oas = load_openapi_project(ctx)
    scan = FastApiAdapter().scan(ctx, "svc")
    twin = assemble_twin(openapi=oas, routes=scan)
    by = {v.state: v for v in twin.states}
    assert by[TwinState.DECLARED].present
    assert by[TwinState.IMPLEMENTED].present
    assert not by[TwinState.DESIRED].present
    assert not by[TwinState.OBSERVED].present
    assert not by[TwinState.HYPOTHETICAL].present
    # absent states carry unknowns, never silent
    assert by[TwinState.OBSERVED].unknowns
    assert twin.unknowns


def test_twin_empty_project(tmp_path: Path) -> None:
    _project(tmp_path, {"x.txt": "nothing"})
    twin = assemble_twin()
    assert all(not v.present for v in twin.states)
    assert len(twin.unknowns) == 5


def test_state_fingerprints_deterministic(tmp_path: Path) -> None:
    files = {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    }
    ctx1 = _project(tmp_path / "a", files)
    ctx2 = _project(tmp_path / "b", files)
    t1 = assemble_twin(openapi=load_openapi_project(ctx1))
    t2 = assemble_twin(openapi=load_openapi_project(ctx2))
    assert t1.view(TwinState.DECLARED).fingerprint == \
        t2.view(TwinState.DECLARED).fingerprint


# ---------- drift ----------


def test_contract_drift_both_directions(tmp_path: Path) -> None:
    ctx = _project(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"
            "  /b:\n    get:\n      operationId: b\n"
            "      responses: {'200': {description: ok}}\n"
        ),
        "app.py": (
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/a')\ndef a():\n    pass\n"
            "@app.get('/c')\ndef c():\n    pass\n"
        ),
    })
    oas = load_openapi_project(ctx)
    scan = FastApiAdapter().scan(ctx, "svc")
    drifts = twin_drift(openapi=oas, routes=scan)
    subs = {(d.subject, d.state_a) for d in drifts}
    assert ("GET /b", TwinState.DECLARED) in subs
    assert ("GET /c", TwinState.IMPLEMENTED) in subs
    assert all(d.kind is TwinDriftKind.CONTRACT_DRIFT for d in drifts)


def test_auth_drift_via_security_model(tmp_path: Path) -> None:
    ctx = _project(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      security:\n        - oauth: []\n"
            "      responses: {'200': {description: ok}}\n"
            "components:\n  securitySchemes:\n"
            "    oauth: {type: oauth2, flows: {}}\n"
        ),
        "app.py": (
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/a')\ndef a():\n    pass\n"
        ),
    })
    oas = load_openapi_project(ctx)
    scan = FastApiAdapter().scan(ctx, "svc")
    sec = load_security_model(ctx, list(ctx.iter_files()),
                              openapi=oas, routes=scan)
    drifts = twin_drift(security=sec)
    assert drifts
    assert drifts[0].kind is TwinDriftKind.AUTH_DRIFT


def test_routing_drift_gateway_path_not_in_contract(tmp_path: Path) -> None:
    ctx = _project(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"
        ),
        "gateway.yaml": "routes:\n  - /a\n  - /internal/secret\n",
    })
    oas = load_openapi_project(ctx)
    drifts = twin_drift(openapi=oas, context=ctx,
                        files=list(ctx.iter_files()))
    subs = {d.subject for d in drifts
            if d.kind is TwinDriftKind.ROUTING_DRIFT}
    assert "/internal/secret" in subs
    assert "/a" not in subs


def test_runtime_drift_observed_not_declared(tmp_path: Path) -> None:
    ctx = _project(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    oas = load_openapi_project(ctx)
    execs = (_exec("GET /a", route="/a"),
             _exec("GET /ghost", route="/ghost"))
    drifts = twin_drift(openapi=oas, executions=execs)
    subs = {d.subject for d in drifts
            if d.kind is TwinDriftKind.RUNTIME_DRIFT}
    assert "/ghost" in subs
    assert "/a" not in subs


def test_slo_drift_budget_exhausted() -> None:
    obj = ApiServiceObjective(
        name="avail", metric="availability", target=0.9,
        window="2023-11-14T22",
    )
    execs = tuple(
        _exec("op", status="error" if i < 5 else "ok")
        for i in range(10)
    )
    drifts = twin_drift(objectives=(obj,), executions=execs)
    assert drifts
    assert drifts[0].kind is TwinDriftKind.SLO_DRIFT
    assert drifts[0].state_a is TwinState.DESIRED
    assert drifts[0].state_b is TwinState.OBSERVED


def test_slo_drift_silent_when_insufficient() -> None:
    obj = ApiServiceObjective(
        name="avail", metric="availability", target=0.9,
    )
    drifts = twin_drift(objectives=(obj,), executions=(_exec("a"),))
    assert not [d for d in drifts if d.kind is TwinDriftKind.SLO_DRIFT]


def test_dependency_drift_observed_callee(tmp_path: Path) -> None:
    from forge_doctor_api.analyzers.runtime import DownstreamCall
    ctx = _project(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    oas = load_openapi_project(ctx)
    e = RequestExecution(
        request_id="r", trace_id="t", service="api", operation="op",
        downstream_calls=(
            DownstreamCall(caller="api", callee="payments",
                           operation="charge"),
            DownstreamCall(caller="api", callee=None, operation="?"),
        ),
    )
    drifts = twin_drift(openapi=oas, executions=(e,))
    dep = [d for d in drifts if d.kind is TwinDriftKind.DEPENDENCY_DRIFT]
    assert [d.subject for d in dep] == ["payments"]
    assert dep[0].unknowns


def test_version_drift(tmp_path: Path) -> None:
    from forge_doctor_api.analyzers.runtime import Span
    ctx = _project(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /v1/a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"
        ),
    })
    oas = load_openapi_project(ctx)
    span = Span(service="api", operation="op",
                attributes={"service.version": "v9"})
    drifts = twin_drift(openapi=oas, executions=(_exec("a"),),
                        spans=(span,))
    ver = [d for d in drifts if d.kind is TwinDriftKind.VERSION_DRIFT]
    assert ver and "v9" in ver[0].subject


# ---------- hypothetical isolation + history ----------


def test_hypothetical_never_contaminates_observed() -> None:
    execs = (_exec("op"),)
    twin = assemble_twin(executions=execs,
                         hypothesis_labels=("whatif-1",))
    obs = twin.view(TwinState.OBSERVED)
    hyp = twin.view(TwinState.HYPOTHETICAL)
    assert obs is not None and obs.present and obs.record_count == 1
    assert hyp is not None and hyp.present
    # hypothesis has its own identifiers; observed unchanged
    assert "whatif-1" in hyp.identifiers
    assert "whatif-1" not in obs.identifiers


def test_history_compact_snapshots() -> None:
    hist = ApiTwinHistory()
    twin1 = assemble_twin()
    twin2 = assemble_twin(
        executions=(_exec("a"), _exec("b")),
        hypothesis_labels=("h1",),
    )
    hist = hist.record(TwinSnapshot(
        label="t0", recorded_at="2026-01-01T00:00:00Z",
        states=twin1.states))
    hist = hist.record(TwinSnapshot(
        label="t1", recorded_at="2026-01-02T00:00:00Z",
        states=twin2.states))
    ordered = hist.ordered()
    assert [s.label for s in ordered] == ["t0", "t1"]
    # compact: snapshots hold views (counts+fingerprints), not payloads
    snap_view = ordered[1].states[3]
    assert snap_view.state is TwinState.OBSERVED
    assert snap_view.record_count == 2
    assert snap_view.fingerprint
    serialized = ordered[1].to_dict()
    assert "RequestExecution" not in repr(serialized)


def test_history_deterministic_ordering() -> None:
    hist = ApiTwinHistory()
    for label, ts in (("b", "2026-01-02T00:00:00Z"),
                      ("a", "2026-01-01T00:00:00Z"),
                      ("c", "2026-01-01T00:00:00Z")):
        hist = hist.record(
            TwinSnapshot(label=label, recorded_at=ts, states=()))
    labels = [s.label for s in hist.ordered()]
    assert labels == ["a", "c", "b"]
