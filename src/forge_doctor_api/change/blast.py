"""§68 blast radius: changed operation -> clients -> services -> business paths.

Only evidenced nodes are listed. `client_impact` (spec 009) provides the
client layer; services are the client module identities (a consuming client
*is* the service); business paths come from declared `SensitiveBusinessFlow`
records linked to an operation only by declared evidence (an `x-flow`-style
extension on the operation or a flow name in the path template). Anything
the evidence cannot resolve yields an explicit UNKNOWN entry, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.analyzers.clients import ApiClientModel, ClientCallSite
from forge_doctor_api.analyzers.openapi import OpenApiOperation, OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.model import OperationSource
from forge_doctor_api.checks.client.engine import _path_matches, client_impact
from forge_doctor_api.checks.compat import CompatibilityClass, ContractDiff
from forge_doctor_api.core.models import Model, UnknownFact
from forge_doctor_api.security.model import SensitiveBusinessFlow

_FLOW_EXTENSIONS = ("x-sensitive-flow", "x-business-flow", "x-protected-flow",
                    "x-flow", "x-flows")


@dataclass(frozen=True, kw_only=True)
class BlastRadiusNode(Model):
    """§68 one chain entry: operation -> clients -> services -> business paths."""

    operation: str
    method: str
    path: str
    change_kind: str
    classification: CompatibilityClass
    clients: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    business_paths: tuple[str, ...] = ()
    call_sites: tuple[str, ...] = ()
    confirmed: bool = False
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class BlastRadiusReport(Model):
    nodes: tuple[BlastRadiusNode, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    @property
    def affected_clients(self) -> tuple[str, ...]:
        return tuple(sorted({c for n in self.nodes for c in n.clients}))


def _flow_extensions(op: OpenApiOperation, model: OpenApiProjectModel) -> tuple[str, ...]:
    """Declared `x-flow`-style extension values owned by this operation."""
    out: list[str] = []
    for ext in model.extensions:
        if ext.name not in _FLOW_EXTENSIONS:
            continue
        if ext.owner_pointer == op.pointer or ext.owner_pointer.startswith(op.pointer + "/"):
            value = ext.value
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, list):
                out.extend(v for v in value if isinstance(v, str))
    return tuple(out)


def _flow_names(op: OpenApiOperation, model: OpenApiProjectModel,
                flows: tuple[SensitiveBusinessFlow, ...]) -> tuple[str, ...]:
    """Declared linkage only: extension value or flow name in the path template."""
    linked = set(_flow_extensions(op, model))
    path_tokens = {t for t in op.path.split("/") if t}
    for flow in flows:
        if flow.name in linked or flow.name in path_tokens:
            linked.add(flow.name)
    linked &= {f.name for f in flows}
    return tuple(sorted(linked))


def _node_for(
    op: OpenApiOperation | None, subject: str, change_kind: str,
    classification: CompatibilityClass, model: OpenApiProjectModel,
    matching: list[ClientCallSite], flows: tuple[SensitiveBusinessFlow, ...],
    confirmed: bool,
) -> BlastRadiusNode:
    client_names = tuple(sorted({s.client for s in matching}))
    if op is None:
        fact = UnknownFact(
            subject=subject,
            missing="changed subject not found in the old contract",
            resolution="provide the pre-change contract so the operation can be matched",
        )
        return BlastRadiusNode(
            operation=subject, method="", path="", change_kind=change_kind,
            classification=classification, unknowns=(fact,),
        )
    return BlastRadiusNode(
        operation=op.identity,
        method=op.method,
        path=op.path,
        change_kind=change_kind,
        classification=classification,
        clients=client_names,
        services=client_names,  # client module identity == consuming service
        business_paths=_flow_names(op, model, flows),
        call_sites=tuple(
            f"{s.client}:{s.location.path}:{s.location.line or 0}"
            for s in matching
        ),
        confirmed=confirmed,
    )


def _matching_sites(op: OpenApiOperation, clients: ApiClientModel) -> list[ClientCallSite]:
    return [
        s
        for s in clients.call_sites
        if s.path is not None
        and _path_matches(op.path, s.path)
        and (s.method is None or s.method == op.method)
    ]


def blast_radius(
    diff: ContractDiff,
    old_model: OpenApiProjectModel,
    clients: ApiClientModel,
    flows: tuple[SensitiveBusinessFlow, ...] = (),
) -> BlastRadiusReport:
    """§68 chain for every non-NON_BREAKING change subject."""
    impact = client_impact(diff, clients, old_model)
    ops = {
        op.identity: op
        for op in old_model.operations
        if op.source is OperationSource.PATH
    }
    nodes: list[BlastRadiusNode] = []
    unknowns: list[UnknownFact] = []
    seen: set[str] = set()

    for entry in impact.entries:
        op = ops.get(entry.operation)
        seen.add(entry.operation)
        matching = _matching_sites(op, clients) if op else []
        nodes.append(_node_for(
            op, entry.operation, entry.change_kind, entry.classification,
            old_model, matching, flows, entry.confirmed,
        ))

    for change in diff.changes:
        if change.classification is CompatibilityClass.NON_BREAKING:
            continue
        op = ops.get(change.subject)
        if op is None:
            fact = UnknownFact(
                subject=change.subject,
                missing="changed subject not found in the old contract",
                resolution="provide the pre-change contract so the operation can be matched",
            )
            unknowns.append(fact)
            if change.subject not in seen:
                seen.add(change.subject)
                nodes.append(_node_for(
                    None, change.subject, change.kind, change.classification,
                    old_model, [], flows, False,
                ))
            continue
        if op.identity in seen:
            continue
        seen.add(op.identity)
        nodes.append(_node_for(
            op, change.subject, change.kind, change.classification,
            old_model, _matching_sites(op, clients), flows, False,
        ))

    nodes.sort(key=lambda n: (n.operation, n.change_kind))
    return BlastRadiusReport(nodes=tuple(nodes), unknowns=tuple(unknowns))
