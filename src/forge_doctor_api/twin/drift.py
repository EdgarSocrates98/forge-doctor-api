"""Twin drift detection (§64).

Every drift finding names the *pair* of states that disagree and cites
evidence on both sides - drift is never asserted within one state.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.routes.model import RouteModel, RouteScan
from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    UnknownFact,
)
from forge_doctor_api.reliability.model import ApiServiceObjective
from forge_doctor_api.reliability.slo import error_budget
from forge_doctor_api.security.model import ApiSecurityModel
from forge_doctor_api.security.scan import normalize_route_path
from forge_doctor_api.twin.model import TwinDrift, TwinDriftKind, TwinState

_VERSION_ATTRS = ("service.version", "api.version", "app.version",
                  "service_version")
_URI_VERSION_RE = re.compile(r"/v(\d+)(?:/|$)")
_ROUTE_KEYS = ("routes", "route", "route_config", "prefix", "path",
               "path_prefix", "match")


def _ev(kind: EvidenceKind, source: str, summary: str,
        line: int | None = None) -> tuple[Evidence, ...]:
    return (Evidence(kind=kind, source=source, summary=summary, line=line),)


def _norm_op_path(path: str) -> str:
    return normalize_route_path(path)


def _route_path_set(routes: RouteScan) -> dict[tuple[str, str], RouteModel]:
    return {
        (r.method.upper(), _norm_op_path(r.path)): r for r in routes.routes
    }


def contract_drift(
    openapi: OpenApiProjectModel, routes: RouteScan
) -> tuple[TwinDrift, ...]:
    """DECLARED vs IMPLEMENTED: ops with no route / routes with no op."""
    if routes is None:
        return ()
    impl = _route_path_set(routes)
    declared = {
        (op.method.upper(), _norm_op_path(op.path)): op
        for op in openapi.operations
    }
    out: list[TwinDrift] = []
    for key in sorted(set(declared) - set(impl)):
        op = declared[key]
        out.append(
            TwinDrift(
                kind=TwinDriftKind.CONTRACT_DRIFT,
                state_a=TwinState.DECLARED,
                state_b=TwinState.IMPLEMENTED,
                subject=f"{key[0]} {key[1]}",
                detail="declared operation has no implemented route",
                evidence_a=_ev(EvidenceKind.STATIC, op.location.path,
                               "declared op", op.location.line),
            )
        )
    for key in sorted(set(impl) - set(declared)):
        r = impl[key]
        out.append(
            TwinDrift(
                kind=TwinDriftKind.CONTRACT_DRIFT,
                state_a=TwinState.IMPLEMENTED,
                state_b=TwinState.DECLARED,
                subject=f"{key[0]} {key[1]}",
                detail="implemented route has no declared operation",
                evidence_a=_ev(EvidenceKind.STATIC, r.source_location.path,
                               "impl route", r.source_location.line),
            )
        )
    return tuple(out)


def auth_drift_entries(security: ApiSecurityModel) -> tuple[TwinDrift, ...]:
    """§53/§64 auth drift -> contract vs impl/gateway plane pairs."""
    out = [
        TwinDrift(
            kind=TwinDriftKind.AUTH_DRIFT,
            state_a=TwinState.DECLARED,
            state_b=TwinState.IMPLEMENTED,
            subject=d.operation,
            detail=d.detail,
            evidence_a=d.evidence,
        )
        for d in security.auth_drift
    ]
    return tuple(sorted(out, key=lambda x: x.subject))


def _gateway_routes(context: ProjectContext, files: list[str]) -> dict[str, str]:
    """Gateway routing prefixes/paths declared in config artifacts."""
    found: dict[str, str] = {}
    for path in sorted(files):
        if Path(path).suffix.lower() not in {".yaml", ".yml", ".json"}:
            continue
        try:
            doc = yaml.safe_load(context.read_text(path))
        except Exception:
            continue
        _collect_routes(doc, path, found)
    return found


def _collect_routes(node: Any, path: str, out: dict[str, str],
                    depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(node, dict):
        for k in _ROUTE_KEYS:
            v = node.get(k)
            if isinstance(v, str) and v.startswith("/"):
                out.setdefault(v, path)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.startswith("/"):
                        out.setdefault(item, path)
        for v in node.values():
            _collect_routes(v, path, out, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_routes(item, path, out, depth + 1)


def routing_drift(
    openapi: OpenApiProjectModel,
    context: ProjectContext,
    files: list[str],
) -> tuple[TwinDrift, ...]:
    """DECLARED vs DECLARED-config: gateway routes absent from contract."""
    gw = _gateway_routes(context, files)
    declared = {_norm_op_path(op.path) for op in openapi.operations}
    out = [
        TwinDrift(
            kind=TwinDriftKind.ROUTING_DRIFT,
            state_a=TwinState.DECLARED,
            state_b=TwinState.DECLARED,
            subject=path,
            detail="gateway route has no declared contract operation",
            evidence_a=_ev(EvidenceKind.CONFIG, src, "gateway route"),
            unknowns=(
                UnknownFact(
                    subject=path,
                    missing="matching contract operation",
                    resolution="confirm whether the route fronts an "
                    "undocumented upstream",
                ),
            ),
        )
        for path, src in sorted(gw.items())
        if _norm_op_path(path) not in declared
        and _norm_op_path(path) != "/"
    ]
    return tuple(out)


def version_drift(
    openapi: OpenApiProjectModel,
    executions: tuple[RequestExecution, ...] | None,
    spans: tuple[Any, ...] = (),
) -> tuple[TwinDrift, ...]:
    """DECLARED api version vs OBSERVED service.version span attrs."""
    declared_versions: set[str] = set()
    for doc in openapi.documents:
        if doc.api_version:
            declared_versions.add(str(doc.api_version))
    for op in openapi.operations:
        m = _URI_VERSION_RE.search(op.path)
        if m:
            declared_versions.add(f"v{m.group(1)}")
    observed: dict[str, str] = {}
    for span in spans:
        for key in _VERSION_ATTRS:
            val = span.attributes.get(key)
            if val:
                observed[val] = key
    out: list[TwinDrift] = []
    for ver in sorted(observed):
        if declared_versions and ver not in declared_versions:
            out.append(
                TwinDrift(
                    kind=TwinDriftKind.VERSION_DRIFT,
                    state_a=TwinState.DECLARED,
                    state_b=TwinState.OBSERVED,
                    subject=ver,
                    detail=f"observed version {ver} not in declared "
                    f"versions {sorted(declared_versions)}",
                    evidence_b=_ev(EvidenceKind.RUNTIME,
                                   "(spans)", f"{observed[ver]}={ver}"),
                )
            )
    return tuple(out)


def runtime_drift(
    openapi: OpenApiProjectModel,
    executions: tuple[RequestExecution, ...] | None,
) -> tuple[TwinDrift, ...]:
    """DECLARED vs OBSERVED operation coverage - both directions."""
    if not executions:
        return ()
    declared_paths = {_norm_op_path(op.path) for op in openapi.operations}
    declared_ops = {op.operation_id for op in openapi.operations
                    if op.operation_id}
    observed: dict[str, RequestExecution] = {}
    for e in executions:
        observed.setdefault(e.route or e.operation, e)
    out: list[TwinDrift] = []
    for key in sorted(observed):
        e = observed[key]
        norm = _norm_op_path(key) if key.startswith("/") else key
        if norm not in declared_paths and e.operation not in declared_ops:
            out.append(
                TwinDrift(
                    kind=TwinDriftKind.RUNTIME_DRIFT,
                    state_a=TwinState.OBSERVED,
                    state_b=TwinState.DECLARED,
                    subject=key,
                    detail="observed operation absent from declared "
                    "contract",
                    evidence_a=_ev(
                        EvidenceKind.RUNTIME,
                        e.evidence[0].source if e.evidence else "(runtime)",
                        f"observed {key}",
                    ),
                )
            )
    return tuple(out)


def slo_drift(
    objectives: tuple[ApiServiceObjective, ...],
    executions: tuple[RequestExecution, ...] | None,
) -> tuple[TwinDrift, ...]:
    """DESIRED objectives vs OBSERVED budget consumption."""
    if not objectives or not executions:
        return ()
    out: list[TwinDrift] = []
    for obj in sorted(objectives, key=lambda o: o.name):
        budget = error_budget(obj, executions)
        if not budget.sufficient:
            continue  # unknown, not drift - insufficient window (§47)
        if budget.remaining < 0:
            out.append(
                TwinDrift(
                    kind=TwinDriftKind.SLO_DRIFT,
                    state_a=TwinState.DESIRED,
                    state_b=TwinState.OBSERVED,
                    subject=obj.name,
                    detail=f"error budget exhausted: consumed "
                    f"{budget.consumed} over target {obj.target} in "
                    f"window {budget.window}",
                    evidence_b=_ev(EvidenceKind.RUNTIME, "(executions)",
                                   f"{budget.total} requests"),
                )
            )
    return tuple(out)


def dependency_drift(
    security: ApiSecurityModel | None,
    openapi: OpenApiProjectModel | None,
    executions: tuple[RequestExecution, ...] | None,
) -> tuple[TwinDrift, ...]:
    """OBSERVED downstream callees absent from declared dependencies."""
    if not executions:
        return ()
    declared_hosts: set[str] = set()
    if security is not None:
        declared_hosts.update(e.host for e in security.external_apis)
    if openapi is not None:
        for s in openapi.servers:
            host = re.sub(r"^https?://", "", s.url).split("/")[0]
            if host:
                declared_hosts.add(host)
    callees: dict[str, RequestExecution] = {}
    for e in executions:
        for d in e.downstream_calls:
            if d.callee:
                callees.setdefault(d.callee, e)
    out = [
        TwinDrift(
            kind=TwinDriftKind.DEPENDENCY_DRIFT,
            state_a=TwinState.OBSERVED,
            state_b=TwinState.DECLARED,
            subject=callee,
            detail="observed downstream callee has no declared "
            "dependency evidence",
            evidence_a=_ev(
                EvidenceKind.RUNTIME,
                callees[callee].evidence[0].source
                if callees[callee].evidence else "(runtime)",
                f"calls to {callee}",
            ),
            unknowns=(
                UnknownFact(
                    subject=callee,
                    missing="declared dependency record",
                    resolution="declare the dependency in contract "
                    "servers or external-api config",
                ),
            ),
        )
        for callee in sorted(callees)
        if callee not in declared_hosts
    ]
    return tuple(out)


def twin_drift(
    openapi: OpenApiProjectModel | None = None,
    routes: RouteScan | None = None,
    security: ApiSecurityModel | None = None,
    executions: tuple[RequestExecution, ...] | None = None,
    objectives: tuple[ApiServiceObjective, ...] = (),
    context: ProjectContext | None = None,
    files: list[str] | None = None,
    spans: tuple[Any, ...] = (),
) -> tuple[TwinDrift, ...]:
    """All §64 drift types; each finding cites its state pair."""
    out: list[TwinDrift] = []
    if openapi is not None and routes is not None:
        out.extend(contract_drift(openapi, routes))
    if security is not None:
        out.extend(auth_drift_entries(security))
    if openapi is not None and context is not None:
        out.extend(routing_drift(openapi, context, files or []))
    if openapi is not None:
        out.extend(version_drift(openapi, executions, spans))
        out.extend(runtime_drift(openapi, executions))
    out.extend(slo_drift(objectives, executions))
    out.extend(dependency_drift(security, openapi, executions))
    return tuple(
        sorted(out, key=lambda d: (d.kind.value, d.subject))
    )
