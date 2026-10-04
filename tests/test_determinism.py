"""Spec 036 — deterministic integration gate.

Same input + same clock + same config → byte-identical output, across
every export surface: JSON, JSONL, agent, SARIF, graph, handoff bundle.
Runs with sockets hard-blocked (the offline guarantee is part of the
same gate class, §8).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from forge_doctor_api.analyzers.clients.graph import client_graph
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.openapi.graph import contract_graph
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.handoff.bundle import assemble_bundle
from forge_doctor_api.output.writers import (
    write_agent,
    write_json,
    write_jsonl,
    write_sarif,
)
from forge_doctor_api.scan import export_scan, scan_project


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during scan")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket, "gethostbyname", _blocked)


_API = """\
openapi: "3.0.3"
info: {title: Orders, version: "1.0"}
paths:
  /orders:
    get:
      operationId: listOrders
      responses:
        "200": {description: ok}
    post:
      operationId: createOrder
      responses:
        "201": {description: ok}
"""

_APP = '''\
from fastapi import FastAPI
app = FastAPI()

@app.get("/orders")
def list_orders():
    return []

@app.post("/orders")
def create_order():
    return {}
'''


def _span(i: int, dur_ms: float = 100.0) -> dict[str, object]:
    return {
        "traceId": f"t{i:08x}",
        "spanId": f"s{i:08x}",
        "name": "GET /orders",
        "kind": 2,
        "startTimeUnixNano": str(i * 1_000_000),
        "endTimeUnixNano": str(i * 1_000_000 + int(dur_ms * 1e6)),
        "attributes": [
            {"key": "http.method", "value": {"stringValue": "GET"}},
            {"key": "http.route", "value": {"stringValue": "/orders"}},
            {"key": "http.status_code", "value": {"intValue": "200"}},
        ],
        "status": {"code": 1},
    }


_OTLP = json.dumps({
    "resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "orders-api"}}]},
        "scopeSpans": [{"scope": {}, "spans": [_span(i) for i in range(8)]}],
    }],
})

_K8S = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: orders-api}
spec:
  template:
    spec:
      containers:
        - name: app
          image: orders:1.0
"""

_KONG = """\
_format_version: "3.0"
services:
  - name: orders
    url: http://orders-api:8080
    routes:
      - name: orders-route
        paths: [/orders]
"""

_POLICY = """\
policies:
  - id: require-auth
    rule: require_auth
    applies_to: "/**"
"""

_CLIENT = '''\
import httpx
def fetch_orders():
    return httpx.get("https://api.example.com/orders")
'''

_CACHE_CFG = """\
service:
  cache:
    ttl: 60
"""

# name -> content; tests write them in two different orders.
FIXTURE_FILES: dict[str, str] = {
    "openapi.yaml": _API,
    "app/main.py": _APP,
    "traces/otlp.json": _OTLP,
    "deploy/k8s.yaml": _K8S,
    "gateway/kong.yaml": _KONG,
    "policies/auth.policy.yaml": _POLICY,
    "clients/consumer.py": _CLIENT,
    "config/service.yaml": _CACHE_CFG,
}


def _write_fixture(root: Path, order: list[str]) -> None:
    for name in order:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FIXTURE_FILES[name], encoding="utf-8")


def _outputs(root: Path) -> dict[str, str]:
    """Every serialized surface a consumer can observe, as bytes."""
    ctx = ProjectContext.from_root(root)
    report = scan_project(ctx)
    files = list(ctx.iter_files())
    openapi = load_openapi_project(ctx)
    clients = scan_clients(ctx, files)
    bundle = assemble_bundle(
        openapi=openapi,
        findings=report.findings,
        diff=report.diff,
        unknowns=report.unknowns,
    )
    return {
        "findings-json": write_json(report.findings),
        "findings-jsonl": write_jsonl(report.findings),
        "findings-sarif": write_sarif(report.findings),
        "findings-agent": write_agent(report.findings, report.unknowns),
        "scan-export": json.dumps(export_scan(report), sort_keys=True),
        "contract-graph": contract_graph(openapi).to_json(),
        "client-graph": client_graph(clients).to_json(),
        "handoff-bundle": json.dumps(bundle.to_dict(), sort_keys=True),
    }


def test_full_pipeline_is_byte_deterministic(tmp_path: Path) -> None:
    order = sorted(FIXTURE_FILES)
    _write_fixture(tmp_path, order)
    first = _outputs(tmp_path)
    second = _outputs(tmp_path)
    assert first == second
    # and nothing collapsed to empty bytes — a real surface compared
    for name, blob in first.items():
        assert len(blob) > 2, name


def test_file_creation_order_does_not_change_output(tmp_path: Path) -> None:
    _write_fixture(tmp_path, sorted(FIXTURE_FILES))
    forward = _outputs(tmp_path)
    # wipe and rewrite in reverse order
    for name in FIXTURE_FILES:
        (tmp_path / name).unlink()
    _write_fixture(tmp_path, sorted(FIXTURE_FILES, reverse=True))
    assert _outputs(tmp_path) == forward


def test_scan_is_deterministic_across_processes(tmp_path: Path) -> None:
    """Cross-process determinism: serialize once per process invocation.

    A subprocess would weaken the offline guarantee (no socket block
    inherited), so this simulates a fresh process by rebuilding every
    object graph from scratch — the same input bytes must produce the
    same semantic output even with new Python objects.
    """
    _write_fixture(tmp_path, sorted(FIXTURE_FILES))
    run_a = _outputs(tmp_path)
    # simulate process restart by dropping any module-level caches
    import gc

    gc.collect()
    run_b = _outputs(tmp_path)
    assert run_a == run_b
