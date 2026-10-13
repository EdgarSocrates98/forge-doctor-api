"""Spec 060 — migration dependency graph over declared evidence.

Units are operations; edges exist only where declared evidence links
them:

- ``schema-dep``: two operations referencing the same
  ``#/components/schemas/...`` component via declared pointers
  (request-body or response pointers). A shared *name substring* never
  creates an edge — only the declared pointer does.
- ``version-dep``: operations on the same path tail under adjacent
  version pins (``/v1/x`` -> ``/v2/x``).
- ``client-impact``: client call sites whose literal method+path match
  an operation.

Cycles are surfaced as ``cycle`` unknowns — ordering is never silently
broken.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    Model,
    UnknownFact,
)


class MigrationEdgeKind(StrEnum):
    SCHEMA_DEP = "schema-dep"
    VERSION_DEP = "version-dep"
    CLIENT_IMPACT = "client-impact"


class Readiness(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class MigrationNode(Model):
    unit_id: str               # "METHOD /path" or "client:{name}"
    readiness: Readiness
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class MigrationEdge(Model):
    from_id: str
    to_id: str
    kind: MigrationEdgeKind
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class MigrationGraph(Model):
    nodes: tuple[MigrationNode, ...]
    edges: tuple[MigrationEdge, ...]
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class MigrationPath(Model):
    """One ordered migration candidate with edge evidence."""

    units: tuple[str, ...]
    edge_evidence: tuple[Evidence, ...]
    remaining_blockers: tuple[str, ...] = ()
    ordering_known: bool = True  # False when a cycle was involved


_VERSION_SEG = re.compile(r"^v(\d+)$")


def _unit(op: object) -> str:
    return f"{op.method.upper()} {op.path}"  # type: ignore[attr-defined]


def _schema_refs(model: OpenApiProjectModel) -> dict[str, str]:
    """component name -> declaring document path."""
    return {s.name: s.location.path for s in model.schemas}


_SCHEMA_REF = "#/components/schemas/"


def _op_schemas(model: OpenApiProjectModel) -> dict[str, set[str]]:
    """operation unit -> declared schema components it references.

    Only resolved `$ref` records whose pointer lives under the
    operation's own pointer count — never name similarity.
    """
    known = set(_schema_refs(model))
    out: dict[str, set[str]] = {}
    ops = {op.pointer: _unit(op) for op in model.operations}
    for ref in model.references:
        if not ref.ref.startswith(_SCHEMA_REF):
            continue
        name = ref.ref[len(_SCHEMA_REF):]
        if name not in known:
            continue
        for op_ptr, unit in ops.items():
            if ref.pointer == op_ptr or ref.pointer.startswith(
                    op_ptr + "/"):
                out.setdefault(unit, set()).add(name)
    return out


def _ev(source: str, summary: str) -> Evidence:
    return Evidence(kind=EvidenceKind.STATIC, source=source,
                    summary=summary)


def build_migration_graph(
    model: OpenApiProjectModel,
    clients: ApiClientModel | None = None,
) -> MigrationGraph:
    """Operations + clients as nodes; declared deps as edges."""
    known_schemas = _schema_refs(model)
    nodes: dict[str, MigrationNode] = {}
    edges: list[MigrationEdge] = []

    for op in model.operations:
        unit = _unit(op)
        blockers: list[str] = []
        if op.deprecated:
            blockers.append("deprecated")
        nodes[unit] = MigrationNode(
            unit_id=unit,
            readiness=(Readiness.BLOCKED if blockers
                       else Readiness.READY),
            blockers=tuple(sorted(blockers)))

    # schema-dep: shared declared component between operations
    op_schemas = _op_schemas(model)
    for op in model.operations:
        op_schemas.setdefault(_unit(op), set())
    units = sorted(op_schemas)
    for i, a in enumerate(units):
        for b in units[i + 1:]:
            shared = sorted(op_schemas[a] & op_schemas[b])
            if shared:
                edges.append(MigrationEdge(
                    from_id=a, to_id=b,
                    kind=MigrationEdgeKind.SCHEMA_DEP,
                    evidence=(
                        _ev(known_schemas[shared[0]],
                            f"shared schema {shared[0]}"),)))

    # version-dep: same tail under adjacent /vN/ prefixes
    by_tail: dict[str, list[tuple[str, int]]] = {}
    for op in model.operations:
        segs = [s for s in op.path.split("/") if s]
        if len(segs) < 2:
            continue
        vm = _VERSION_SEG.match(segs[0])
        if vm:
            tail = "/" + "/".join(segs[1:])
            by_tail.setdefault(tail, []).append(
                (_unit(op), int(vm.group(1))))
    for tail, entries in sorted(by_tail.items()):
        by_ver: dict[int, list[str]] = {}
        for unit, ver in entries:
            by_ver.setdefault(ver, []).append(unit)
        vers = sorted(by_ver)
        for va, vb in itertools.pairwise(vers):
            for ua in by_ver[va]:
                for ub in by_ver[vb]:
                    edges.append(MigrationEdge(
                        from_id=ua, to_id=ub,
                        kind=MigrationEdgeKind.VERSION_DEP,
                        evidence=(
                            _ev("paths",
                                f"v{va} -> v{vb} on {tail}"),)))

    # client-impact: literal call-site hits on operations
    if clients is not None:
        op_by_path: dict[str, list[str]] = {}
        for op in model.operations:
            op_by_path.setdefault(op.path, []).append(_unit(op))
        for site in clients.call_sites:
            if site.path is None:
                continue
            for unit in op_by_path.get(site.path, ()):
                if site.method and unit.split(" ", 1)[0] != site.method.upper():
                    continue
                cnode = f"client:{site.client}"
                nodes.setdefault(cnode, MigrationNode(
                    unit_id=cnode, readiness=Readiness.READY))
                edges.append(MigrationEdge(
                    from_id=cnode, to_id=unit,
                    kind=MigrationEdgeKind.CLIENT_IMPACT,
                    evidence=(
                        _ev(site.location.path,
                            f"call site {site.method or '?'} "
                            f"{site.path}"),)))

    return MigrationGraph(
        nodes=tuple(nodes[u] for u in sorted(nodes)),
        edges=tuple(sorted(
            edges, key=lambda e: (e.from_id, e.kind.value, e.to_id))))


def migration_paths(graph: MigrationGraph) -> tuple[MigrationPath, ...]:
    """Ordered candidates: dependency edges topologically sorted.

    Cycles break the ordering claim: the remaining units are emitted
    as one path with `ordering_known=False`, never silently dropped.
    """
    dep_kinds = {MigrationEdgeKind.SCHEMA_DEP,
                 MigrationEdgeKind.VERSION_DEP}
    out: dict[str, set[str]] = {}
    ev: list[Evidence] = []
    for e in graph.edges:
        if e.kind in dep_kinds:
            out.setdefault(e.from_id, set()).add(e.to_id)
            ev.extend(e.evidence)
    units = {n.unit_id for n in graph.nodes
             if not n.unit_id.startswith("client:")}
    # Kahn on the dep subgraph (a depends on b? order b first? — we
    # order shared-schema dependents AFTER their linked units by
    # treating edges as 'migrate from -> migrate to')
    indeg = {u: 0 for u in units}
    adj: dict[str, set[str]] = {u: set() for u in units}
    for a, targets in out.items():
        for b in targets:
            if b in units and a in units:
                adj[a].add(b)
                indeg[b] += 1
    ready = sorted(u for u in units if indeg[u] == 0)
    order: list[str] = []
    while ready:
        u = ready.pop(0)
        order.append(u)
        for v in sorted(adj[u]):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
                ready.sort()
    cyclic = sorted(u for u in units if u not in set(order))
    paths: list[MigrationPath] = []
    if order:
        paths.append(MigrationPath(
            units=tuple(order), edge_evidence=tuple(ev),
            remaining_blockers=tuple(sorted(
                b for n in graph.nodes for b in n.blockers
                if n.unit_id in set(order)))))
    if cyclic:
        paths.append(MigrationPath(
            units=tuple(cyclic), edge_evidence=tuple(ev),
            ordering_known=False,
            remaining_blockers=tuple(sorted(
                b for n in graph.nodes for b in n.blockers
                if n.unit_id in set(cyclic)))))
    return tuple(paths)
