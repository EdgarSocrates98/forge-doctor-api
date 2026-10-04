"""Spec 030 — hermetic/offline proofs + streaming-scale + retention.

Network is disabled for the whole module: any socket creation raises.
`test_package.py` already proves no module imports socket/urllib/http;
this suite proves scans keep working when sockets are hard-blocked.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from forge_doctor_api.analyzers.runtime.execution import (
    executions_from_traces,
)
from forge_doctor_api.analyzers.runtime.loader import load_runtime_project
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.scan import scan_project


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any socket construction inside the scan path is a hard failure."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during offline scan")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket, "gethostbyname", _blocked)


_API = """\
openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /items:
    get:
      operationId: listItems
      responses:
        "200": {description: ok}
"""


def _span(i: int, dur_ms: float = 100.0) -> dict[str, object]:
    return {
        "traceId": f"t{i:08x}",
        "spanId": f"s{i:08x}",
        "name": "GET /items",
        "kind": 2,
        "startTimeUnixNano": "0",
        "endTimeUnixNano": str(int(dur_ms * 1e6)),
        "attributes": [
            {"key": "http.method", "value": {"stringValue": "GET"}},
            {"key": "http.route", "value": {"stringValue": "/items"}},
            {"key": "http.status_code", "value": {"intValue": "200"}},
        ],
        "status": {"code": 1},
    }


def _otlp(count: int) -> str:
    return json.dumps({
        "resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": "api"}}]},
            "scopeSpans": [{"scope": {}, "spans": [_span(i) for i in range(count)]}],
        }],
    })


def test_scan_project_runs_offline(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(_API, encoding="utf-8")
    (tmp_path / "traces.json").write_text(_otlp(50), encoding="utf-8")
    report = scan_project(ProjectContext.from_root(tmp_path))
    assert report.findings or report.unknowns or report.gate_passed


@pytest.mark.parametrize("count", [1_000, 10_000])
def test_streaming_ingestion_scale(tmp_path: Path, count: int) -> None:
    """§181 — span streams normalize; raw span retention is opt-in."""
    (tmp_path / "traces.json").write_text(_otlp(count), encoding="utf-8")
    ctx = ProjectContext.from_root(tmp_path)
    # default mode drops raw spans but still yields executions
    dropped = load_runtime_project(ctx, ["traces.json"], keep_spans=False)
    assert sum(len(t.spans) for t in dropped.traces) == 0
    assert len(dropped.executions) == count
    # kept spans normalize to executions at scale
    rt = load_runtime_project(ctx, ["traces.json"], keep_spans=True)
    assert len(rt.executions) == count


def test_compact_history_storage(tmp_path: Path) -> None:
    """§87 — RequestHistory keeps summary executions, never span payloads."""
    from forge_doctor_api.analyzers.runtime.history import RequestHistory
    (tmp_path / "traces.json").write_text(_otlp(500), encoding="utf-8")
    rt = load_runtime_project(
        ProjectContext.from_root(tmp_path), ["traces.json"], keep_spans=True)
    executions, _ = executions_from_traces(rt.traces)
    history = RequestHistory()
    history.add_all(executions)
    blob = json.dumps([e.to_dict() for e in executions])
    # a raw span would carry OTLP payload fields; executions keep only
    # summary scalars + evidence refs
    assert "startTimeUnixNano" not in blob
    assert "stringValue" not in blob
    assert '"spans"' not in blob
    assert len(blob) < 2_000_000
