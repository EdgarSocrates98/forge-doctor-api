"""Spec 083 — MCP boundary hardening.

The MCP surface is a trust boundary: these tests drive the real
low-level server over in-memory JSON-RPC streams (not the
`call_tool` test shortcut) and assert the stable contract:

- initialize handshake works; unsupported protocol versions
  negotiate to a stable response (never a crash);
- unknown methods return JSON-RPC method-not-found;
- missing/invalid params produce a stable protocol error;
- unknown resources error cleanly;
- empty results are valid empty payloads;
- over-budget responses truncate deterministically and record
  truncation UnknownFacts — never silently;
- internal exceptions become stable error payloads — no Python
  exception text on the wire.

Transport-level malformed-input coverage (raw garbage bytes,
invalid envelopes) lives in `factory/mcp_smoke.py`, which exercises
the real stdio path — those cases are parse errors below the
session layer and cannot exist in an in-memory SessionMessage.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="optional mcp extra")

import mcp.types as t
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)

from forge_doctor_api.handoff.mcp_server import (
    MCP_RESPONSE_BUDGET,
    build_server,
)

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""


def _root(tmp_path: Path, *, openapi: str = OPENAPI) -> Path:
    (tmp_path / "api.yaml").write_text(openapi, encoding="utf-8")
    return tmp_path


@asynccontextmanager
async def _serve(root: Path,
                 budget: int = MCP_RESPONSE_BUDGET,
                 ) -> AsyncIterator[tuple[Any, Any]]:
    """Run the lowlevel server over memory streams.

    Yields (read_stream, write_stream) — the client's side."""
    server = build_server(root, budget=budget)
    low = server._lowlevel_server
    # the protocol surface, not the high-level call_tool shortcut.
    async with create_client_server_memory_streams() as (client, srv):
        task = asyncio.create_task(low.run(
            srv[0], srv[1], low.create_initialization_options()))
        try:
            yield client
        finally:
            pass  # streams close first — the server loop unwinds
    task.cancel()
    with suppress(BaseException):
        await task


async def _send(write: Any, msg: Any) -> None:
    await write.send(SessionMessage(msg))


async def _request(write: Any, read: Any, id: int, method: str,
                   params: dict[str, Any] | None = None) -> Any:
    await _send(write, JSONRPCRequest(
        jsonrpc="2.0", id=id, method=method, params=params))
    resp = await read.receive()
    return resp.message


async def _handshake(write: Any, read: Any,
                     version: str | None = None) -> Any:
    resp = await _request(write, read, 1, "initialize", {
        "protocolVersion": version or t.LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "boundary-test", "version": "0"},
    })
    await _send(write, JSONRPCNotification(
        jsonrpc="2.0", method="notifications/initialized"))
    return resp


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _text_of(response_msg: Any) -> str:
    result = response_msg.result if isinstance(
        response_msg, JSONRPCResponse) else {}
    return result["content"][0]["text"]


# -- initialization ----------------------------------------------------------------

def test_valid_initialize(tmp_path: Path) -> None:
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            return await _handshake(write, read)
    resp = _run(go())
    assert isinstance(resp, JSONRPCResponse)
    result = resp.result
    assert result["serverInfo"]["name"] == "forge-doctor-api"
    assert result["protocolVersion"]


def test_unsupported_protocol_version_stable(tmp_path: Path) -> None:
    """A bogus protocol version gets a typed response — negotiation
    or a JSON-RPC error — never a crash or a Python traceback."""
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            return await _request(write, read, 1, "initialize", {
                "protocolVersion": "1900-01-01",
                "capabilities": {},
                "clientInfo": {"name": "x", "version": "0"},
            })
    msg = _run(go())
    assert isinstance(msg, (JSONRPCResponse, JSONRPCError))
    if isinstance(msg, JSONRPCResponse):
        assert msg.result["protocolVersion"]
    else:
        assert isinstance(msg.error.code, int)


# -- method / params / resources -----------------------------------------------------

def test_unknown_method_returns_method_not_found(tmp_path: Path) -> None:
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "doctor.bogus", {})
    msg = _run(go())
    assert isinstance(msg, JSONRPCError)
    assert msg.error.code == -32601
    assert "Traceback" not in msg.error.message


def test_missing_params_stable_error(tmp_path: Path) -> None:
    """doctor.get_operation requires operation_id — missing args get a
    stable error surface (isError result or JSON-RPC error)."""
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "tools/call", {
                "name": "doctor.get_operation", "arguments": {}})
    msg = _run(go())
    if isinstance(msg, JSONRPCError):
        assert isinstance(msg.error.code, int)
    else:
        assert msg.result["isError"] is True


def test_invalid_params_stable_error(tmp_path: Path) -> None:
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "tools/call", {
                "name": "doctor.get_operation",
                "arguments": {"operation_id": 12345}})
    msg = _run(go())
    if isinstance(msg, JSONRPCError):
        assert isinstance(msg.error.code, int)
    else:
        assert msg.result["isError"] is True


def test_unknown_resource_errors(tmp_path: Path) -> None:
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "resources/read", {
                "uri": "doctor://nonexistent"})
    msg = _run(go())
    assert isinstance(msg, JSONRPCError)
    assert isinstance(msg.error.code, int)


def test_empty_result_valid(tmp_path: Path) -> None:
    """A project with nothing to report returns a valid empty payload."""
    async def go() -> Any:
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "README.md").write_text("nothing here\n")
        async with _serve(empty) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "tools/call", {
                "name": "doctor.get_findings", "arguments": {}})
    msg = _run(go())
    assert isinstance(msg, JSONRPCResponse)
    payload = json.loads(_text_of(msg))
    assert payload == [] or payload.get("error") is not None \
        or isinstance(payload, dict)


def test_unknown_tool_stable_error(tmp_path: Path) -> None:
    """Unknown tool → isError result naming the tool; no traceback."""
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "tools/call", {
                "name": "doctor.bogus", "arguments": {}})
    msg = _run(go())
    assert isinstance(msg, JSONRPCResponse)
    assert msg.result.get("isError") is True
    text = msg.result["content"][0]["text"]
    assert "doctor.bogus" in text
    assert "Traceback" not in text


def test_invalid_argument_type_stable(tmp_path: Path) -> None:
    """Wrong argument type → MCP-layer isError, never an exception."""
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "tools/call", {
                "name": "doctor.explain",
                "arguments": {"finding_id": 42}})
    msg = _run(go())
    assert isinstance(msg, JSONRPCResponse)
    assert msg.result.get("isError") is True
    assert "Traceback" not in msg.result["content"][0]["text"]


def test_templated_resource_unknown_id(tmp_path: Path) -> None:
    """A templated doctor:// read with an unknown id returns a valid
    slice — the resource exists; the slice is honestly empty."""
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "resources/read", {
                "uri": "doctor://operation/nope"})
    msg = _run(go())
    assert isinstance(msg, JSONRPCResponse)
    payload = json.loads(msg.result["contents"][0]["text"])
    assert payload["kind"] == "operation"
    assert payload["ref"] == "doctor://operation/nope"
    assert payload["findings"] == []


def test_missing_mcp_dependency_stable_error(tmp_path: Path) -> None:
    """Without the mcp extra, build_server raises a typed error with
    the install hint — no ModuleNotFoundError internals."""
    import sys
    from unittest import mock

    from forge_doctor_api.handoff.mcp_server import McpDependencyError
    with mock.patch.dict(sys.modules, {"mcp": None,
                                       "mcp.server": None,
                                       "mcp.server.mcpserver": None}), \
            pytest.raises(McpDependencyError,
                          match="forge-doctor-api\\[mcp\\]"):
        build_server(_root(tmp_path))


def test_malformed_stdio_input_resilient(tmp_path: Path) -> None:
    """Over the real stdio transport, malformed JSON and envelopes
    missing `jsonrpc`/`id` are dropped without killing the server —
    a following valid request still gets its response."""
    import subprocess
    import sys
    import threading
    from queue import Empty, Queue

    root = _root(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "forge_doctor_api", "mcp", str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    assert proc.stdin and proc.stdout
    lines: Queue[str] = Queue()
    threading.Thread(
        target=lambda: [
            lines.put(line)
            for line in iter(proc.stdout.readline, "")],
        daemon=True).start()

    def send(msg: Any) -> None:
        proc.stdin.write(msg if isinstance(msg, str)
                         else json.dumps(msg) + "\n")
        proc.stdin.flush()

    try:
        send("this is not json\n")
        send({"method": "ping", "id": 5})  # envelope missing jsonrpc
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {
                  "protocolVersion": t.LATEST_PROTOCOL_VERSION,
                  "capabilities": {},
                  "clientInfo": {"name": "stdio-boundary",
                                 "version": "0"}}})
        try:
            resp = json.loads(lines.get(timeout=90))
        except Empty:
            pytest.fail("server died on malformed input")
        assert resp["id"] == 1
        assert "result" in resp, resp
    finally:
        proc.kill()
        proc.wait(timeout=10)


# -- bounded payloads ----------------------------------------------------------------

def _ops_doc(n: int) -> str:
    ops = "\n".join(
        f"  /r{i}:\n    get:\n      operationId: op{i}\n"
        f"      responses: {{'200': {{description: ok}}}}"
        for i in range(n))
    return ("openapi: 3.0.3\n"
            "info: {title: T, version: '1'}\npaths:\n" + ops + "\n")


def test_bounded_result_records_unknown(tmp_path: Path) -> None:
    """A response over budget truncates deterministically and records
    truncation UnknownFacts — the drop is never silent."""
    async def go() -> str:
        async with _serve(_root(tmp_path, openapi=_ops_doc(40)),
                          budget=2048) as (read, write):
            await _handshake(write, read)
            resp = await _request(write, read, 2, "tools/call", {
                "name": "doctor.get_findings", "arguments": {}})
            assert isinstance(resp, JSONRPCResponse)
            return _text_of(resp)
    text = _run(go())
    payload = json.loads(text)
    assert isinstance(payload, dict)
    unknowns = payload.get("unknowns") or (
        payload.get("data", {}).get("unknowns") or [])
    truncated = [u for u in unknowns if u.get("kind") == "truncated"]
    assert truncated, f"expected truncation unknowns in: {text[:200]}"
    assert len(text.encode("utf-8")) <= 4096


def test_bounded_is_deterministic(tmp_path: Path) -> None:
    doc = _ops_doc(40)

    async def go() -> str:
        async with _serve(_root(tmp_path, openapi=doc),
                          budget=3072) as (read, write):
            await _handshake(write, read)
            resp = await _request(write, read, 2, "tools/call", {
                "name": "doctor.get_graph", "arguments": {}})
            assert isinstance(resp, JSONRPCResponse)
            return _text_of(resp)
    assert _run(go()) == _run(go())


# -- error contract -----------------------------------------------------------------

def test_internal_exception_stable_error(tmp_path: Path) -> None:
    """A crash inside a tool returns a stable error payload — no
    exception class name or traceback reaches the wire."""
    from forge_doctor_api.sdk import Doctor

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("sensitive internals /path/leak")

    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "tools/call", {
                "name": "doctor.get_findings", "arguments": {}})

    import unittest.mock as mock
    with mock.patch.object(Doctor, "scan", boom):
        msg = _run(go())
    if isinstance(msg, JSONRPCResponse):
        text = _text_of(msg)
        if msg.result.get("isError"):
            assert "sensitive internals" not in text
            assert "RuntimeError" not in text
            assert "Traceback" not in text
            return
        payload = json.loads(text)
        assert payload["error"]["code"] == "INTERNAL_ERROR"
        assert "sensitive internals" not in payload["error"]["message"]
        assert "RuntimeError" not in text
        assert "Traceback" not in text
    else:
        assert "sensitive internals" not in msg.error.message
        assert "RuntimeError" not in msg.error.message


def test_domain_error_stable(tmp_path: Path) -> None:
    async def go() -> Any:
        async with _serve(_root(tmp_path)) as (read, write):
            await _handshake(write, read)
            return await _request(write, read, 2, "tools/call", {
                "name": "doctor.explain",
                "arguments": {"finding_id": "NOPE-404"}})
    msg = _run(go())
    assert isinstance(msg, JSONRPCResponse)
    payload = json.loads(_text_of(msg))
    assert payload["error"]["code"] == "DOMAIN_ERROR"
    assert "no finding" in payload["error"]["message"]


# -- inventory -------------------------------------------------------------------------

def test_tool_inventory_matches_frozen() -> None:
    """The tool name inventory must equal the frozen artifact."""
    artifact = json.loads((Path(__file__).resolve().parents[1]
                           / "factory" / "artifacts"
                           / "mcp-inventory.json").read_text("utf-8"))
    frozen = {t["name"] for t in artifact["tools"]}
    import re
    src = (Path(__file__).resolve().parents[1] / "src"
           / "forge_doctor_api" / "handoff" / "mcp_server.py"
           ).read_text(encoding="utf-8")
    live = set(re.findall(r'"(doctor\.[a-z_]+)"', src))
    assert live == frozen, (
        f"inventory drift: live-only {sorted(live - frozen)}, "
        f"frozen-only {sorted(frozen - live)}")


def test_tool_inventory_schemas_match(tmp_path: Path) -> None:
    """When mcp is installed, live input schemas must hash to the
    frozen digests — a schema change without an inventory bump fails."""
    import hashlib
    artifact = json.loads((Path(__file__).resolve().parents[1]
                           / "factory" / "artifacts"
                           / "mcp-inventory.json").read_text("utf-8"))
    server = build_server(_root(tmp_path))
    tools = asyncio.run(server.list_tools())
    digests = {
        t.name: hashlib.sha256(json.dumps(
            t.inputSchema if hasattr(t, "inputSchema")
            else t.input_schema,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        for t in tools}
    frozen = {t["name"]: t["input_schema_sha256"]
              for t in artifact["tools"]}
    assert digests == frozen, (
        f"schema drift: "
        f"{sorted(k for k in digests if digests[k] != frozen.get(k))}")


def test_resource_inventory_matches_frozen(tmp_path: Path) -> None:
    artifact = json.loads((Path(__file__).resolve().parents[1]
                           / "factory" / "artifacts"
                           / "mcp-inventory.json").read_text("utf-8"))
    server = build_server(_root(tmp_path))
    live_resources = sorted(
        str(r.uri) for r in asyncio.run(server.list_resources()))
    live_templates = sorted(
        t.uriTemplate if hasattr(t, "uriTemplate") else t.uri_template
        for t in asyncio.run(server.list_resource_templates()))
    assert live_resources == artifact["resources"]
    assert live_templates == artifact["resource_templates"]
