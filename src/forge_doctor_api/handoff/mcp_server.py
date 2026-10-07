"""§133/§216 real MCP server over the Doctor facade.

Deterministic + offline: tools return compact JSON text (never raw
payloads), resources serve `doctor://` slices. stdio is the default
transport — a socket-blocked environment still serves the protocol.

Boundary contract (spec 083):

- Errors are data — every tool/resource failure returns
  ``{"error": {"code", "message", "evidence"?}}`` with a stable code
  (``DOMAIN_ERROR``, ``INTERNAL_ERROR``, ``RESPONSE_TOO_LARGE``);
  Python exception details never escape into payloads.
- Responses are bounded — payloads over ``MCP_RESPONSE_BUDGET`` bytes
  are deterministically truncated (largest top-level collections
  first, order preserved) and every cut is recorded as an
  ``UnknownFact`` in an ``unknowns`` field. Over-budget payloads emit
  ``{"data": ..., "unknowns": [...]}``; nothing is dropped silently.

Requires the optional `mcp` extra (`pip install forge-doctor-api[mcp]`).
The `mcp` package is imported lazily so the rest of the product works
without it; its decorators are untyped at the boundary.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from forge_doctor_api.contracts.models import UnknownFact
from forge_doctor_api.handoff.context import context_slice, mint
from forge_doctor_api.sdk import Doctor, DoctorError

_SERVER_NAME = "forge-doctor-api"

_MCP_IMPORT_ERROR = (
    "the `mcp` package is required for the MCP server — "
    "install with: pip install 'forge-doctor-api[mcp]'"
)

# Response budget per tool/resource call. Sized for agent context
# windows; the deterministic truncator records what it dropped.
MCP_RESPONSE_BUDGET = 256 * 1024


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
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _error(code: str, message: str,
           evidence: list[str] | None = None) -> str:
    """Stable error payload — the only shape failures take."""
    err: dict[str, Any] = {"code": code, "message": message}
    if evidence:
        err["evidence"] = list(evidence)
    return _text({"error": err})


def _truncation(subject: str, field: str, kept: int, total: int,
                budget: int) -> UnknownFact:
    return UnknownFact(
        subject=f"{subject}.{field}" if field else subject,
        kind="truncated",
        reason=f"bounded to {kept} of {total} items under "
               f"{budget}B response budget",
        source=_SERVER_NAME)


def _bounded(payload: Any, subject: str, budget: int) -> str:
    """Serialize `payload`, truncating deterministically when over
    `budget` bytes; every truncation is recorded as an UnknownFact."""
    data = payload.to_dict() if hasattr(payload, "to_dict") else payload
    text = _text(data)
    if len(text.encode("utf-8")) <= budget:
        return text

    notes: list[UnknownFact] = []
    original_unknowns = (
        list(data["unknowns"])
        if isinstance(data, dict)
        and isinstance(data.get("unknowns"), list)
        else [])
    if isinstance(data, dict):
        work: dict[str, Any] = {
            k: (list(v) if isinstance(v, list) else v)
            for k, v in data.items()}
    else:
        work = {"items": data if isinstance(data, list)
                else [data]}

    while len(text.encode("utf-8")) > budget:
        fields = sorted(
            (k for k, v in work.items()
             if isinstance(v, list) and v and k != "unknowns"),
            key=lambda k: (-len(_text(work[k])), k))
        if not fields:
            return _error(
                "RESPONSE_TOO_LARGE",
                f"{subject} exceeds {budget}B with no truncatable "
                "collection")
        key = fields[0]
        items = work[key]
        keep = len(items) // 2
        work[key] = items[:keep]
        notes.append(_truncation(subject, key, keep, len(items),
                                 budget))
        work["unknowns"] = [
            *original_unknowns,
            *(u.to_dict() for u in notes)]
        text = _text(work)
    return text


def _guard(fn: Callable[..., Any], name: str,
           budget: int) -> Callable[..., str]:
    """Boundary wrapper: stable errors + bounded payloads.

    The wrapped signature is preserved so the MCP layer derives the
    input schema from the real parameters, not from ``*args``."""
    def _inner(*args: Any, **kwargs: Any) -> str:
        try:
            return _bounded(fn(*args, **kwargs), name, budget)
        except DoctorError as exc:
            return _error("DOMAIN_ERROR", str(exc))
        except Exception:
            return _error("INTERNAL_ERROR", f"{name} failed")
    _inner.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    _inner.__name__ = name.replace(".", "_").replace("-", "_")
    return _inner


def build_server(root: str | Path, *, clock: Any = None,
                 budget: int = MCP_RESPONSE_BUDGET) -> Any:
    """MCP server exposing Doctor tools + doctor:// resources."""
    from forge_doctor_api.core.context import ProjectContext
    from forge_doctor_api.handoff.mcp import DoctorApi

    server_cls = _require_mcp()
    doctor = Doctor.from_path(root, clock=clock)
    api = DoctorApi(ProjectContext.from_root(Path(root).resolve()))
    server = server_cls(_SERVER_NAME)

    def _tool(fn: Callable[..., Any], name: str, doc: str) -> None:
        inner = _guard(fn, name, budget)
        inner.__doc__ = doc
        server.add_tool(inner, name=name, description=doc,
                        structured_output=False)

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

    def _operation(operation_id: str) -> Any:
        return api.get_operation(operation_id)

    server.add_tool(
        _guard(_operation, "doctor.get_operation", budget),
        name="doctor.get_operation",
        description="one operation by id/identity",
        structured_output=False)

    def _explain(finding_id: str) -> Any:
        return doctor.explain(finding_id)

    server.add_tool(
        _guard(_explain, "doctor.explain", budget),
        name="doctor.explain",
        description="finding + evidence + why it fired",
        structured_output=False)

    # -- resources (doctor:// slices) -----------------------------------------

    def _res(fn: Callable[..., Any], name: str) -> Callable[..., str]:
        inner = _guard(fn, name, budget)
        inner.__doc__ = f"doctor:// slice: {name}"
        return inner

    @server.resource("doctor://service")
    def _service() -> str:
        return _res(lambda: context_slice(doctor.scan(),
                                          mint("service")),
                    "doctor://service")()

    @server.resource("doctor://graph")
    def _graph() -> str:
        return _res(lambda: context_slice(doctor.scan(),
                                          mint("graph")),
                    "doctor://graph")()

    @server.resource("doctor://unknowns")
    def _unknowns() -> str:
        return _res(lambda: {"unknowns": [
            u.to_dict() for u in doctor.scan().unknowns]},
            "doctor://unknowns")()

    @server.resource("doctor://service/{sid}")
    def _service_id(sid: str) -> str:
        return _res(lambda: context_slice(
            doctor.scan(), f"doctor://service/{sid}"),
            f"doctor://service/{sid}")()

    @server.resource("doctor://operation/{op}")
    def _op_resource(op: str) -> str:
        return _res(lambda: context_slice(
            doctor.scan(), f"doctor://operation/{op}"),
            f"doctor://operation/{op}")()

    @server.resource("doctor://finding/{ref}")
    def _finding(ref: str) -> str:
        return _res(lambda: context_slice(
            doctor.scan(), f"doctor://finding/{ref}"),
            f"doctor://finding/{ref}")()

    @server.resource("doctor://handoff/{hid}")
    def _handoff(hid: str) -> str:
        return _res(lambda: {
            "handoff_id": hid,
            "bundle": doctor.handoff().to_dict()},
            f"doctor://handoff/{hid}")()

    return server


def serve_stdio(root: str | Path, *, clock: Any = None) -> None:
    """Run the stdio transport (blocks until the client disconnects)."""
    import asyncio

    server = build_server(root, clock=clock)
    asyncio.run(server.run_stdio_async())
