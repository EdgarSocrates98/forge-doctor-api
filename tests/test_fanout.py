"""Spec 031 — fanout signal (§59)."""

from __future__ import annotations

import pytest

from forge_doctor_api.analyzers.clients.model import (
    ApiClientModel,
    ClientCallSite,
    ClientLanguage,
)
from forge_doctor_api.analyzers.routes.model import RouteModel, RouteScan
from forge_doctor_api.analyzers.runtime.execution import (
    DownstreamCall,
    RequestExecution,
)
from forge_doctor_api.core.models import EvidenceKind, SourceLocation
from forge_doctor_api.perf.fanout import (
    FanoutSignal,
    FanoutStatus,
    fanout_signals,
)

_LOC = SourceLocation(path="app.py", line=1)
_OTHER = SourceLocation(path="other.py", line=1)


def _route(path: str, file: str = "app.py") -> RouteModel:
    return RouteModel(
        framework="fastapi", service="svc", method="GET", path=path,
        handler=f"svc.h_{path.strip('/') or 'root'}",
        source_location=SourceLocation(path=file, line=10))


def _site(url: str, file: str = "app.py") -> ClientCallSite:
    return ClientCallSite(
        client="cli", language=ClientLanguage.PYTHON, library="requests",
        method="GET", url=url, path=None, location=SourceLocation(path=file))


def _exec(op: str, callees: tuple[str, ...]) -> RequestExecution:
    return RequestExecution(
        request_id="r1", trace_id="t1", service="svc", operation=op,
        downstream_calls=tuple(
            DownstreamCall(caller="svc", callee=c, operation=f"op_{c}")
            for c in callees))


def _scan(*routes: RouteModel) -> RouteScan:
    return RouteScan(service="svc", routes=routes)


def _clients(*sites: ClientCallSite) -> ApiClientModel:
    return ApiClientModel(call_sites=sites)


class TestStaticTier:
    def test_single_handler_file_gets_candidate_width(self) -> None:
        sigs = fanout_signals(
            _scan(_route("/x")),
            _clients(_site("https://a.internal/x"), _site("https://b.internal/x")))
        assert len(sigs) == 1
        sig = sigs[0]
        assert sig.subject == "GET /x"
        assert sig.status is FanoutStatus.CANDIDATE
        assert sig.static_width == 2
        assert sig.runtime_width is None
        assert sig.evidence[0].kind is EvidenceKind.STATIC

    def test_no_call_sites_no_rows(self) -> None:
        assert fanout_signals(_scan(_route("/x")), _clients()) == ()

    def test_ambiguous_attribution_records_unknown(self) -> None:
        scan = _scan(
            RouteModel(framework="fastapi", service="svc", method="GET",
                       path="/a", handler="svc.a",
                       source_location=SourceLocation(path="app.py", line=1)),
            RouteModel(framework="fastapi", service="svc", method="GET",
                       path="/b", handler="svc.b",
                       source_location=SourceLocation(path="app.py", line=9)))
        sigs = fanout_signals(scan, _clients(_site("https://a.internal/x")))
        assert len(sigs) == 2
        for sig in sigs:
            assert sig.static_width is None
            assert sig.unknowns
            assert "attribution" in sig.unknowns[0].missing


class TestRuntimeTier:
    def test_runtime_only_is_confirmed(self) -> None:
        sigs = fanout_signals(
            _scan(), _clients(),
            executions=(_exec("GET /x", ("db", "mq")),
                        _exec("GET /x", ("db",))))
        assert sigs[0].status is FanoutStatus.CONFIRMED
        assert sigs[0].runtime_width == 2
        assert sigs[0].static_width is None
        assert sigs[0].evidence[0].kind is EvidenceKind.RUNTIME


class TestMerged:
    def test_static_plus_runtime(self) -> None:
        sigs = fanout_signals(
            _scan(_route("/x")),
            _clients(_site("https://a.internal/x")),
            executions=(_exec("GET /x", ("a.internal", "b")),))
        sig = sigs[0]
        assert sig.status is FanoutStatus.CONFIRMED
        assert sig.static_width == 1
        assert sig.runtime_width == 2
        assert {e.kind for e in sig.evidence} == {
            EvidenceKind.STATIC, EvidenceKind.RUNTIME}

    def test_requested_subject_without_evidence_is_empty_candidate(self) -> None:
        sigs = fanout_signals(
            _scan(), _clients(), subjects=("GET /unmeasured",))
        sig = sigs[0]
        assert sig.status is FanoutStatus.CANDIDATE
        assert sig.static_width is None and sig.runtime_width is None

    def test_deterministic(self) -> None:
        clients = _clients(_site("https://b.internal/x"),
                           _site("https://a.internal/x"))
        a = fanout_signals(_scan(_route("/x")), clients)
        b = fanout_signals(_scan(_route("/x")), clients)
        assert a == b
        assert a[0].to_dict()["subject"] == "GET /x"

    def test_frozen(self) -> None:
        sig = FanoutSignal(subject="s", status=FanoutStatus.CANDIDATE)
        with pytest.raises(AttributeError):
            sig.static_width = 9  # type: ignore[misc]
