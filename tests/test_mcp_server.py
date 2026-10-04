"""Spec 045 — real MCP server: tools, resources, stdio smoke."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from forge_doctor_api.handoff.mcp_server import build_server

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""

mcp = pytest.importorskip("mcp", reason="optional mcp extra")


def _root(tmp_path: Path) -> Path:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def server(tmp_path: Path):
    return build_server(_root(tmp_path))


def test_tools_registered(server) -> None:
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    expected = {
        "doctor.scan", "doctor.get_service", "doctor.get_api",
        "doctor.get_operation", "doctor.get_contract",
        "doctor.get_clients", "doctor.get_runtime",
        "doctor.get_security", "doctor.get_reliability",
        "doctor.get_findings", "doctor.get_unknowns",
        "doctor.get_breaking_changes", "doctor.get_blast_radius",
        "doctor.get_capabilities", "doctor.get_graph",
        "doctor.get_handoff", "doctor.explain",
    }
    assert expected <= names


def test_resources_registered(server) -> None:
    resources = asyncio.run(server.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "doctor://service" in uris
    assert "doctor://graph" in uris
    assert "doctor://unknowns" in uris
    templates = asyncio.run(server.list_resource_templates())
    tpl_uris = {t.uri_template for t in templates}
    assert any("operation" in u for u in tpl_uris)
    assert any("finding" in u for u in tpl_uris)
    assert any("handoff" in u for u in tpl_uris)


def test_tool_schema_valid(server) -> None:
    tools = asyncio.run(server.list_tools())
    for t in tools:
        assert t.input_schema["type"] == "object"


def test_scan_tool_round_trip(server) -> None:
    result = asyncio.run(server.call_tool("doctor.scan", {}))
    text = result[0][0].text if isinstance(result, tuple) else (
        result.content[0].text)
    payload = json.loads(text)
    assert payload["schema_version"]
    assert payload["contracts"] is not None


def test_explain_tool_error_is_typed(server) -> None:
    result = asyncio.run(
        server.call_tool("doctor.explain", {"finding_id": "NOPE-9"}))
    text = result[0][0].text if isinstance(result, tuple) else (
        result.content[0].text)
    assert "no finding" in json.loads(text)["error"]


def test_service_resource(server) -> None:
    rows = list(asyncio.run(
        server.read_resource("doctor://service")))
    payload = json.loads(rows[0].content)
    assert payload["kind"] == "service"


def test_tool_deterministic(server) -> None:
    a = asyncio.run(server.call_tool("doctor.scan", {}))
    b = asyncio.run(server.call_tool("doctor.scan", {}))
    ta = a[0][0].text if isinstance(a, tuple) else a.content[0].text
    tb = b[0][0].text if isinstance(b, tuple) else b.content[0].text
    assert ta == tb
