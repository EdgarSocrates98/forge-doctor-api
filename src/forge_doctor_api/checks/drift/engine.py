"""`ApiContractDrift` engine (§14, §143-§146, §181-§182).

Compares an `OpenApiProjectModel` (spec 004) with a `RouteScan` (spec 006)
without reparsing either. Pairing follows §181: `operationId` correlates
against the handler's terminal function name (FastAPI's generated
operationId), else `method + normalized path`. Normalization is §182-
conservative: `{param}` names are compared as evidence — structurally equal
paths pair up, but differing template variable names surface as DRIFT004
rather than being silently merged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiParameter,
    OpenApiProjectModel,
    OpenApiResponse,
    OperationSource,
)
from forge_doctor_api.analyzers.routes.model import RouteModel, RouteScan
from forge_doctor_api.checks.drift.catalog import BY_ID, ContractAuthority, DriftCheckSpec
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Model,
    Severity,
    SourceLocation,
    UnknownFact,
)

_TEMPLATE = re.compile(r"\{([^{}/]+)\}")
_REF_SHAPE = re.compile(r"^ref:.*/(?P<name>[^/]+)$")
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def normalize_path(path: str) -> str:
    """Structural normalization (§182): strip trailing '/', erase `{var}` names."""
    return _TEMPLATE.sub("{}", path.rstrip("/") or "/")


def path_vars(path: str) -> tuple[str, ...]:
    return tuple(_TEMPLATE.findall(path))


@dataclass(frozen=True, kw_only=True)
class ApiErrorModel(Model):
    """§146 — HTTP error surface on each side of the contract."""

    contract_error_statuses: tuple[str, ...] = ()
    impl_error_statuses: tuple[str, ...] = ()
    contract_error_shapes: tuple[str, ...] = ()
    impl_error_shapes_known: bool = False
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DriftPair(Model):
    """A matched operation ↔ route, plus how it was matched."""

    operation_identity: str
    handler: str
    matched_by: str  # "identity" | "path"


@dataclass(frozen=True, kw_only=True)
class DriftReport(Model):
    findings: tuple[Finding, ...] = ()
    matched: tuple[DriftPair, ...] = ()
    unmatched_operations: tuple[str, ...] = ()
    unmatched_routes: tuple[str, ...] = ()
    error_model: ApiErrorModel = ApiErrorModel()


def _evidence(route: RouteModel | None, loc: SourceLocation, summary: str) -> tuple[Evidence, ...]:
    out = [
        Evidence(
            kind=EvidenceKind.STATIC, source=loc.path, summary=summary, line=loc.line
        )
    ]
    if route is not None:
        out.append(
            Evidence(
                kind=EvidenceKind.STATIC,
                source=route.source_location.path,
                summary=f"implementation: {route.method} {route.path} -> {route.handler}",
                line=route.source_location.line,
            )
        )
    return tuple(out)


def _finding(
    spec: DriftCheckSpec,
    *,
    description: str,
    location: SourceLocation,
    entity_ids: tuple[str, ...],
    route: RouteModel | None = None,
    severity: Severity | None = None,
    confidence: Confidence | None = None,
    remediation: str | None = None,
    unknowns: tuple[UnknownFact, ...] = (),
) -> Finding:
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity if severity is None else severity,
        confidence=spec.confidence if confidence is None else confidence,
        evidence_kind=spec.evidence_kind,
        evidence=_evidence(route, location, description),
        entity_ids=entity_ids,
        source_location=location,
        remediation=remediation,
        unknowns=unknowns,
    )


def _authority_unknown(authority: ContractAuthority) -> tuple[UnknownFact, ...]:
    if authority in (ContractAuthority.OPENAPI, ContractAuthority.IMPLEMENTATION):
        return ()
    return (
        UnknownFact(
            subject="contract_authority",
            missing="which side of the drift is authoritative",
            resolution="declare contract_authority: openapi | implementation | gateway | none",
        ),
    )


def _ref_names(shapes: tuple[str, ...]) -> tuple[str, ...]:
    names = set()
    for shape in shapes:
        match = _REF_SHAPE.match(shape)
        if match:
            names.add(match["name"])
    return tuple(sorted(names))


def _op_entity(op: OpenApiOperation) -> str:
    return f"operation:openapi:{op.identity}"


def _route_entity(route: RouteModel) -> str:
    return f"operation:{route.framework}:{route.handler}"


def contract_drift(
    model: OpenApiProjectModel,
    scan: RouteScan,
    authority: ContractAuthority = ContractAuthority.UNDECLARED,
) -> DriftReport:
    params = {(p.location.path, p.pointer): p for p in model.parameters}
    responses = {(r.location.path, r.pointer): r for r in model.responses}
    bodies = {(b.location.path, b.pointer): b for b in model.request_bodies}
    doc_requirements = [
        r for r in model.security_requirements if r.owner_pointer == ""
    ]
    requirements = list(model.security_requirements)

    ops = [o for o in model.operations if o.source is OperationSource.PATH]
    routes = list(scan.routes)

    findings: list[Finding] = []
    matched: list[DriftPair] = []
    unmatched_ops: list[OpenApiOperation] = []
    unmatched_routes: list[RouteModel] = []

    by_key: dict[tuple[str, str], RouteModel] = {}
    by_handler: dict[str, RouteModel] = {}
    path_methods: dict[str, set[str]] = {}
    for route in routes:
        by_key[(route.method, normalize_path(route.path))] = route
        by_handler[route.handler.rsplit(".", 1)[-1]] = route
        path_methods.setdefault(normalize_path(route.path), set()).add(route.method)

    contract_path_methods: dict[str, set[str]] = {}
    for op in ops:
        contract_path_methods.setdefault(normalize_path(op.path), set()).add(op.method)

    def contract_loc(op: OpenApiOperation) -> SourceLocation:
        return op.location

    def unmatched_op_finding(op: OpenApiOperation) -> Finding:
        spec = BY_ID["DRIFT001"]
        norm = normalize_path(op.path)
        impl_methods = sorted(path_methods.get(norm, set()) - {op.method})
        if impl_methods:
            return _finding(
                BY_ID["DRIFT003"],
                description=(
                    f"documented {op.method} {op.path} has no implementation; the path is "
                    f"served by {', '.join(impl_methods)}"
                ),
                location=contract_loc(op),
                entity_ids=(_op_entity(op),),
                unknowns=_authority_unknown(authority),
            )
        return _finding(
            spec,
            description=f"documented {op.method} {op.path} has no implementation",
            location=contract_loc(op),
            entity_ids=(_op_entity(op),),
            severity=(
                Severity.HIGH
                if authority is ContractAuthority.OPENAPI
                else Severity.LOW if authority is ContractAuthority.IMPLEMENTATION
                else Severity.MEDIUM
            ),
            unknowns=_authority_unknown(authority),
            remediation="implement the operation or correct the contract",
        )

    def unmatched_route_findings(route: RouteModel) -> list[Finding]:
        norm = normalize_path(route.path)
        contract_methods = sorted(contract_path_methods.get(norm, set()) - {route.method})
        out: list[Finding] = []
        if contract_methods:
            out.append(
                _finding(
                    BY_ID["DRIFT003"],
                    description=(
                        f"implemented {route.method} {route.path} is undocumented; the path "
                        f"is documented with {', '.join(contract_methods)}"
                    ),
                    location=route.source_location,
                    entity_ids=(_route_entity(route),),
                    route=route,
                    unknowns=_authority_unknown(authority),
                )
            )
            return out
        out.append(
            _finding(
                BY_ID["DRIFT002"],
                description=f"implemented {route.method} {route.path} is absent from the contract",
                location=route.source_location,
                entity_ids=(_route_entity(route),),
                route=route,
                severity=(
                    Severity.MEDIUM
                    if authority is ContractAuthority.OPENAPI
                    else Severity.LOW if authority is ContractAuthority.IMPLEMENTATION
                    else Severity.MEDIUM
                ),
                unknowns=_authority_unknown(authority),
            )
        )
        if route.method in _WRITE_METHODS:
            out.append(
                _finding(
                    BY_ID["DRIFT010"],
                    description=(
                        f"undocumented write operation {route.method} {route.path} is "
                        "implemented — potential breaking surface change"
                    ),
                    location=route.source_location,
                    entity_ids=(_route_entity(route),),
                    route=route,
                    unknowns=_authority_unknown(authority),
                )
            )
        return out

    remaining_routes = dict(by_key)
    remaining_handlers = dict(by_handler)

    for op in sorted(ops, key=lambda o: o.identity):
        key = (op.method, normalize_path(op.path))
        matched_route = remaining_routes.get(key)
        if matched_route is not None:
            remaining_routes.pop(key)
        how = "path"
        if matched_route is None and op.operation_id:
            if op.operation_id in remaining_handlers:
                matched_route = remaining_handlers.pop(op.operation_id)
                how = "identity"
                rkey = (matched_route.method, normalize_path(matched_route.path))
                if rkey in remaining_routes:
                    remaining_routes.pop(rkey)
        elif matched_route is not None:
            tail = matched_route.handler.rsplit(".", 1)[-1]
            if tail in remaining_handlers:
                remaining_handlers.pop(tail)
        if matched_route is None:
            unmatched_ops.append(op)
            continue
        matched.append(
            DriftPair(
                operation_identity=op.identity,
                handler=matched_route.handler,
                matched_by=how,
            )
        )
        findings.extend(
            _pair_findings(
                op,
                matched_route,
                how,
                params,
                responses,
                bodies,
                requirements,
                doc_requirements,
                authority,
            )
        )

    for op in unmatched_ops:
        findings.append(unmatched_op_finding(op))
    for route in sorted(remaining_routes.values(), key=lambda r: (r.path, r.method)):
        unmatched_routes.append(route)
        findings.extend(unmatched_route_findings(route))

    error_model = ApiErrorModel(
        contract_error_statuses=tuple(
            sorted(
                {
                    r.status
                    for r in model.responses
                    if r.status and r.status[:1] in ("4", "5")
                }
            )
        ),
        impl_error_statuses=tuple(
            sorted(
                {
                    code
                    for route in routes
                    for code in route.status_codes
                    if code[:1] in ("4", "5")
                }
            )
        ),
        contract_error_shapes=tuple(
            sorted(
                {
                    shape
                    for r in model.responses
                    if r.status and r.status[:1] in ("4", "5")
                    for shape in r.schema_shapes
                }
            )
        ),
        impl_error_shapes_known=False,
        unknowns=(
            UnknownFact(
                subject="implementation error bodies",
                missing="error response payload shapes from source",
                resolution="runtime evidence (spec 014) or explicit error-schema decorators",
            ),
        ),
    )

    order = {spec.id: i for i, spec in enumerate(BY_ID.values())}
    findings.sort(
        key=lambda f: (
            order.get(f.id, 99),
            f.source_location.path if f.source_location else "",
            f.source_location.line or 0 if f.source_location else 0,
            f.description,
        )
    )
    return DriftReport(
        findings=tuple(findings),
        matched=tuple(matched),
        unmatched_operations=tuple(o.identity for o in unmatched_ops),
        unmatched_routes=tuple(f"{r.method} {r.path}" for r in unmatched_routes),
        error_model=error_model,
    )


def _pair_findings(
    op: OpenApiOperation,
    route: RouteModel,
    matched_by: str,
    params: dict[tuple[str, str], OpenApiParameter],
    responses: dict[tuple[str, str], OpenApiResponse],
    bodies: dict[tuple[str, str], Any],
    requirements: list[Any],
    doc_requirements: list[Any],
    authority: ContractAuthority,
) -> list[Finding]:
    out: list[Finding] = []
    entity_ids = (_op_entity(op), _route_entity(route))

    if matched_by == "identity" and (
        route.method != op.method or normalize_path(route.path) != normalize_path(op.path)
    ):
        out.append(
            _finding(
                BY_ID["DRIFT003"],
                description=(
                    f"operation {op.operation_id!r} is documented as {op.method} "
                    f"{op.path} but implemented as {route.method} {route.path}"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )

    # DRIFT004 — parameter comparison (both directions, every location)
    contract_params = [
        params[(op.location.path, p)]
        for p in op.parameter_pointers
        if (op.location.path, p) in params and params[(op.location.path, p)].name
    ]
    route_params = [p for p in route.parameters if p.location_in != "dependency"]
    contract_vars = set(path_vars(op.path))
    route_vars = set(path_vars(route.path))
    diffs: list[str] = []
    if contract_vars != route_vars:
        diffs.append(
            f"path variables {sorted(contract_vars)} vs {sorted(route_vars)}"
        )
    contract_named: dict[tuple[str, str], OpenApiParameter] = {}
    for p in contract_params:
        if p.name and p.location_in:
            contract_named[(p.name, p.location_in)] = p
    route_named = {(p.name, p.location_in): p for p in route_params}
    for key in sorted(set(contract_named) - set(route_named)):
        name, where = key
        if where == "path" and name in contract_vars and name not in route_vars:
            continue  # already covered by the variable-name diff
        diffs.append(f"contract parameter {name!r} ({where}) missing in implementation")
    for key in sorted(set(route_named) - set(contract_named)):
        name, where = key
        if where == "path" and name in route_vars and name not in contract_vars:
            continue
        diffs.append(f"implemented parameter {name!r} ({where}) absent from contract")
    for key in sorted(set(contract_named) & set(route_named)):
        if contract_named[key].required != route_named[key].required:
            diffs.append(
                f"parameter {key[0]!r} required={contract_named[key].required} in "
                f"contract vs required={route_named[key].required} in implementation"
            )
    if diffs:
        out.append(
            _finding(
                BY_ID["DRIFT004"],
                description=f"{op.method} {op.path}: " + "; ".join(diffs),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )

    # DRIFT005 — request body
    contract_body = bodies.get((op.location.path, op.request_body_pointer or ""))
    contract_body_names = _ref_names(contract_body.schema_shapes) if contract_body else ()
    impl_body = route.request_schema.rsplit(".", 1)[-1] if route.request_schema else None
    if contract_body is not None and contract_body.has_schema and impl_body is None:
        out.append(
            _finding(
                BY_ID["DRIFT005"],
                description=(
                    f"{op.method} {op.path}: contract declares a request schema "
                    f"({', '.join(contract_body_names) or 'inline'}) but the handler takes "
                    "no body model"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )
    elif impl_body is not None and (contract_body is None or not contract_body.has_schema):
        out.append(
            _finding(
                BY_ID["DRIFT005"],
                description=(
                    f"{op.method} {op.path}: handler takes body model {impl_body!r} but "
                    "the contract declares no request schema"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )
    elif impl_body is not None and contract_body_names and impl_body not in contract_body_names:
        out.append(
            _finding(
                BY_ID["DRIFT005"],
                description=(
                    f"{op.method} {op.path}: contract body schema "
                    f"{contract_body_names} vs implementation model {impl_body!r}"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )

    # DRIFT006 — response schema (2xx responses)
    contract_resp_names = {
        name
        for r in (
            responses[(op.location.path, p)]
            for p in op.response_pointers
            if (op.location.path, p) in responses
        )
        if r.status and r.status[:1] == "2"
        for name in _ref_names(r.schema_shapes)
    }
    impl_resp = route.response_schema.rsplit(".", 1)[-1] if route.response_schema else None
    if contract_resp_names and impl_resp and impl_resp not in contract_resp_names:
        out.append(
            _finding(
                BY_ID["DRIFT006"],
                description=(
                    f"{op.method} {op.path}: contract response schema "
                    f"{sorted(contract_resp_names)} vs implementation {impl_resp!r}"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )

    # DRIFT007 — status codes
    contract_statuses = {
        r.status
        for r in (
            responses[(op.location.path, p)]
            for p in op.response_pointers
            if (op.location.path, p) in responses
        )
        if r.status
    }
    numeric_impl = {
        digits
        for s in route.status_codes
        for digits in re.findall(r"\d{3}", s)
    } | {s for s in route.status_codes if s.isdigit()}
    unexpected = sorted(numeric_impl - contract_statuses)
    if unexpected:
        out.append(
            _finding(
                BY_ID["DRIFT007"],
                description=(
                    f"{op.method} {op.path}: implementation declares status codes "
                    f"{unexpected} absent from contract responses {sorted(contract_statuses)}"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )

    # DRIFT008 — auth
    op_reqs = [
        r
        for r in requirements
        if r.owner_pointer == op.pointer and r.location.path == op.location.path
    ]
    doc_reqs = [r for r in doc_requirements if r.location.path == op.location.path]
    effective = op_reqs if op.has_security else doc_reqs
    contract_auth = any(r.schemes for r in effective)
    if contract_auth and not route.auth:
        out.append(
            _finding(
                BY_ID["DRIFT008"],
                description=(
                    f"{op.method} {op.path}: contract requires security but the handler "
                    "shows no Security() dependency evidence"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )
    elif route.auth and not contract_auth:
        out.append(
            _finding(
                BY_ID["DRIFT008"],
                description=(
                    f"{op.method} {op.path}: handler enforces security dependencies "
                    f"{sorted(route.auth)} but the contract requires none"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )

    # DRIFT009 — deprecated contract, live implementation
    if op.deprecated:
        out.append(
            _finding(
                BY_ID["DRIFT009"],
                description=(
                    f"deprecated operation {op.method} {op.path} still has a live route at "
                    f"{route.handler}"
                ),
                location=route.source_location,
                entity_ids=entity_ids,
                route=route,
            )
        )

    return out
