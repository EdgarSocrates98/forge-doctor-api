"""§133/§216 real MCP server over the Doctor facade.

Deterministic + offline: tools return compact JSON text (never raw
payloads), resources serve `doctor://` slices. stdio is the default
transport — a socket-blocked environment still serves the protocol.

Requires the optional `mcp` extra (`pip install forge-doctor-api[mcp]`).
The `mcp` package is imported lazily so the rest of the product works
without it; its decorators are untyped at the boundary.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from forge_doctor_api.handoff.context import context_slice, mint
from forge_doctor_api.sdk import Doctor, DoctorError

_SERVER_NAME = "forge-doctor-api"

_MCP_IMPORT_ERROR = (
    "the `mcp` package is required for the MCP server — "
    "install with: pip install 'forge-doctor-api[mcp]'"
)


class McpDependencyError(ImportError):
    """Raised when the optional `mcp` extra is not installed."""


def _require_mcp() -> Any:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise McpDependencyError(_MCP_IMPORT_ERROR) from exc
    return MCPServer


def _text(payload: Any) -> str:
    """Deterministic compact JSON text content."""
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_server(root: str | Path, *, clock: Any = None) -> Any:
    """MCP server exposing Doctor tools + doctor:// resources."""
    from forge_doctor_api.core.context import ProjectContext
    from forge_doctor_api.handoff.mcp import DoctorApi

    server_cls = _require_mcp()
    doctor = Doctor.from_path(root, clock=clock)
    api = DoctorApi(ProjectContext.from_root(Path(root).resolve()))
    server = server_cls(_SERVER_NAME)

    def _tool(fn: Callable[[], Any], name: str, doc: str) -> None:
        def _inner() -> str:
            return _text(fn())
        _inner.__name__ = name.replace(".", "_").replace("-", "_")
        _inner.__doc__ = doc
        server.add_tool(_inner, name=name, description=doc)

    _tool(lambda: doctor.scan(), "doctor.scan",
          "run the unified deterministic scan")
    _tool(api.get_service, "doctor.get_service",
          "service-level summary: titles, versions, operation counts")
    _tool(api.get_api, "doctor.get_api",
          "contract surface: methods + paths, never payloads")
    _tool(api.get_contract, "doctor.get_contract",
          "contract metadata (doc identity + versions)")
    _tool(api.get_clients, "doctor.get_clients",
          "outbound client call surface")
    _tool(lambda: doctor.scan().runtime, "doctor.get_runtime",
          "runtime DomainSummary (None without runtime evidence)")
    _tool(api.get_security_findings, "doctor.get_security",
          "security model findings surface")
    _tool(api.get_reliability_status, "doctor.get_reliability",
          "reliability model status")
    _tool(lambda: [f.to_dict() for f in doctor.scan().findings],
          "doctor.get_findings", "all scan findings")
    _tool(api.get_unknowns, "doctor.get_unknowns",
          "explicit unknowns across models")
    _tool(api.get_breaking_changes, "doctor.get_breaking_changes",
          "breaking contract changes (needs --before surface)")
    _tool(api.get_blast_radius, "doctor.get_blast_radius",
          "blast radius over non-non-breaking changes")
    _tool(lambda: [c.capability.value for c in doctor.capabilities()],
          "doctor.get_capabilities", "detected capabilities")
    _tool(lambda: doctor.graph(), "doctor.get_graph",
          "graph DomainSummary or null")
    _tool(lambda: doctor.handoff(), "doctor.get_handoff",
          "V2 ApiHandoffBundle")

    def _operation(operation_id: str) -> str:
        return _text(api.get_operation(operation_id))

    server.add_tool(_operation, name="doctor.get_operation",
                    description="one operation by id/identity")

    def _explain(finding_id: str) -> str:
        try:
            return _text(doctor.explain(finding_id))
        except DoctorError as exc:
            return _text({"error": str(exc)})

    server.add_tool(_explain, name="doctor.explain",
                    description="finding + evidence + why it fired")

    # -- resources (doctor:// slices) -----------------------------------------
    @server.resource("doctor://service")
    def _service() -> str:
        return _text(context_slice(doctor.scan(), mint("service")))

    @server.resource("doctor://graph")
    def _graph() -> str:
        return _text(context_slice(doctor.scan(), mint("graph")))

    @server.resource("doctor://unknowns")
    def _unknowns() -> str:
        return _text({"unknowns": [
            u.to_dict() for u in doctor.scan().unknowns]})

    @server.resource("doctor://service/{sid}")
    def _service_id(sid: str) -> str:
        return _text(context_slice(
            doctor.scan(), f"doctor://service/{sid}"))

    @server.resource("doctor://operation/{op}")
    def _op_resource(op: str) -> str:
        return _text(context_slice(
            doctor.scan(), f"doctor://operation/{op}"))

    @server.resource("doctor://finding/{ref}")
    def _finding(ref: str) -> str:
        return _text(context_slice(
            doctor.scan(), f"doctor://finding/{ref}"))

    @server.resource("doctor://handoff/{hid}")
    def _handoff(hid: str) -> str:
        bundle = doctor.handoff()
        return _text({"handoff_id": hid, "bundle": bundle.to_dict()})

    return server


def serve_stdio(root: str | Path, *, clock: Any = None) -> None:
    """Run the stdio transport (blocks until the client disconnects)."""
    import asyncio

    server = build_server(root, clock=clock)
    asyncio.run(server.run_stdio_async())
