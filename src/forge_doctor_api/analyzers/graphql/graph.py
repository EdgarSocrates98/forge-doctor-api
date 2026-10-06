"""GraphQL ServiceGraph materialization (§22, §8.2)."""

from __future__ import annotations

from forge_doctor_api.analyzers.graphql.model import GraphQLProjectModel
from forge_doctor_api.core.graph import ServiceGraph
from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    Evidence,
    EvidenceKind,
    Relationship,
    RelationshipKind,
    SourceLocation,
    entity_id,
)


def graphql_graph(model: GraphQLProjectModel, service: str = "service") -> ServiceGraph:
    """Emit GraphQLType and GraphQLResolver entities + schema relationships."""
    graph = ServiceGraph()
    service_id = entity_id("service", "graphql", service)
    graph.add_entity(Entity(id=service_id, kind="service", name=service))

    seen_edges: set[tuple[str, str, str]] = set()

    def link(
        kind: RelationshipKind, source: str, target: str, loc: SourceLocation
    ) -> None:
        key = (source, kind.value, target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        graph.add_relationship(
            Relationship(
                kind=kind,
                source_id=source,
                target_id=target,
                confidence=Confidence.HIGH,
                evidence=(
                    Evidence(
                        kind=EvidenceKind.STATIC,
                        source=loc.path,
                        summary=f"{kind.value} {target}",
                        line=loc.line,
                    ),
                ),
            )
        )

    type_ids: dict[str, str] = {}
    for t in model.types:
        eid = entity_id("graphql_type", "graphql", f"{t.kind}:{t.name}")
        type_ids[t.name] = eid
        graph.add_entity(
            Entity(
                id=eid,
                kind="graphql_type",
                name=t.name,
                attributes={"type_kind": str(t.kind.value)},
            )
        )
        if t.operation_root is not None:
            link(RelationshipKind.EXPOSES, service_id, eid, t.location)

    for t in model.types:
        # field -> target type containment edges
        for f in t.fields:
            if f.type.name in type_ids and f.type.name != t.name:
                link(
                    RelationshipKind.DEPENDS_ON,
                    type_ids[t.name],
                    type_ids[f.type.name],
                    f.location,
                )
        for member in t.union_members:
            if member in type_ids:
                link(
                    RelationshipKind.EXPOSES, type_ids[t.name], type_ids[member],
                    t.location,
                )
        for iface in t.interfaces:
            if iface in type_ids:
                link(
                    RelationshipKind.IMPLEMENTS,
                    type_ids[t.name],
                    type_ids[iface],
                    t.location,
                )

    for r in model.resolvers:
        rid = entity_id("graphql_resolver", "graphql", f"{r.type_name}.{r.field_name}")
        graph.add_entity(
            Entity(
                id=rid,
                kind="graphql_resolver",
                name=f"{r.type_name}.{r.field_name}",
                attributes={"auth_evidence": "yes" if r.auth_evidence else "no"},
            )
        )
        if r.type_name in type_ids:
            link(
                RelationshipKind.IMPLEMENTS, rid, type_ids[r.type_name], r.location
            )
    return graph
