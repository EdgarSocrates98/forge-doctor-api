"""Spec 083 — cross-surface consistency proof.

One fixture project observed through four public surfaces must yield
the same finding identities, severity, confidence, evidence refs, and
unknown semantics:

1. CLI      — `forge-doctor-api scan --format report` (JSON)
2. SDK      — `Doctor.from_path(root).scan().to_dict()`
3. MCP      — `doctor.scan` tool over the real protocol transport
4. Handoff  — `Doctor.handoff()` V2 bundle projection

Consistency here is what makes the MCP boundary trustworthy: an agent
reading `doctor.scan` sees exactly what a human sees in the CLI and
what a downstream Forger receives in the handoff bundle.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import pytest
import typer.testing

pytest.importorskip("mcp", reason="optional mcp extra")

import mcp.types as t
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCNotification, JSONRPCRequest

from forge_doctor_api.cli import app
from forge_doctor_api.handoff.mcp_server import build_server
from forge_doctor_api.sdk import Doctor

OPENAPI = """\
openapi: 3.0.3
info: {title: CrossSurface, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
  /owners:
    post:
      responses: {"201": {description: created}}
"""


def _root(tmp_path: Path) -> Path:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    return tmp_path


def _finding_sig(f: dict[str, Any]) -> tuple[Any, ...]:
    return (
        f["id"], f["severity"], f["confidence"], f["evidence_kind"],
        tuple(sorted(
            (e.get("kind"), e.get("source"), e.get("line"))
            for e in f.get("evidence", []))),
        tuple(sorted(
            u.get("subject") for u in f.get("unknowns", []))),
    )


def _sigs(report_dict: dict[str, Any]) -> list[tuple[Any, ...]]:
    return sorted(_finding_sig(f) for f in report_dict["findings"])


async def _mcp_scan(root: Path) -> dict[str, Any]:
    server = build_server(root)
    low = server._lowlevel_server
    async with create_client_server_memory_streams() as (client, srv):
        read, write = client
        task = asyncio.create_task(low.run(
            srv[0], srv[1], low.create_initialization_options()))

        async def req(i: int, method: str, params: dict | None = None) -> Any:
            await write.send(SessionMessage(JSONRPCRequest(
                jsonrpc="2.0", id=i, method=method, params=params)))
            return (await read.receive()).message

        await req(1, "initialize", {
            "protocolVersion": t.LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "x-surface", "version": "0"}})
        await write.send(SessionMessage(JSONRPCNotification(
            jsonrpc="2.0", method="notifications/initialized")))
        resp = await req(2, "tools/call",
                         {"name": "doctor.scan", "arguments": {}})
        text = resp.result["content"][0]["text"]
    task.cancel()
    with contextlib.suppress(BaseException):
        await task
    return json.loads(text)


def test_finding_identity_consistent_across_surfaces(
        tmp_path: Path) -> None:
    root = _root(tmp_path)

    runner = typer.testing.CliRunner()
    result = runner.invoke(
        app, ["scan", str(root), "--format", "report"])
    assert result.exit_code == 0, result.output[:500]
    cli_report = json.loads(result.output)

    sdk_report = Doctor.from_path(root).scan().to_dict()
    mcp_report = asyncio.run(_mcp_scan(root))
    handoff = Doctor.from_path(root).handoff().to_dict()

    cli_sigs = _sigs(cli_report)
    assert cli_sigs, "fixture must produce findings"
    assert cli_sigs == _sigs(sdk_report) == _sigs(mcp_report), (
        "CLI/SDK/MCP finding identities diverged")
    assert cli_sigs == _sigs(handoff), (
        "handoff bundle finding identities diverged")


def test_unknown_semantics_survive_all_surfaces(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sdk_report = Doctor.from_path(root).scan().to_dict()
    mcp_report = asyncio.run(_mcp_scan(root))
    handoff = Doctor.from_path(root).handoff().to_dict()

    def unknown_subjects(d: dict[str, Any]) -> set[str]:
        subs = {u["subject"] for u in d.get("unknowns", [])}
        for f in d.get("findings", []):
            subs.update(u.get("subject") for u in f.get("unknowns", []))
        return subs

    sdk_unknowns = unknown_subjects(sdk_report)
    assert unknown_subjects(mcp_report) == sdk_unknowns
    # the handoff projection keeps unknown semantics as explicit
    # entries — every report-level unknown subject is present
    bundle_subjects = {u["subject"] for u in handoff["unknowns"]}
    assert sdk_unknowns <= bundle_subjects or not sdk_unknowns
    assert bundle_subjects  # fixture must exercise unknown plumbing


def test_schema_version_consistent_across_surfaces(
        tmp_path: Path) -> None:
    root = _root(tmp_path)
    sdk_report = Doctor.from_path(root).scan().to_dict()
    mcp_report = asyncio.run(_mcp_scan(root))
    assert sdk_report["schema_version"] == mcp_report["schema_version"]
    assert sdk_report["tool_version"] == mcp_report["tool_version"]
    assert sdk_report["project"] == mcp_report["project"]
