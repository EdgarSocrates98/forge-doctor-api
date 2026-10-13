"""gRPC ServiceGraph materialization (§25, §8.2)."""

from __future__ import annotations

from forge_doctor_api.analyzers.grpc.model import GrpcProjectModel
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


def grpc_graph(model: GrpcProjectModel, service: str = "service") -> ServiceGraph:
    """Emit GrpcService/GrpcMethod/ProtoMessage entities + edges."""
    graph = ServiceGraph()
    service_id = entity_id("service", "grpc", service)
    graph.add_entity(Entity(id=service_id, kind="service", name=service))

    seen: set[tuple[str, str, str]] = set()

    def link(
        kind: RelationshipKind, source: str, target: str, loc: SourceLocation
    ) -> None:
        key = (source, kind.value, target)
        if key in seen:
            return
        seen.add(key)
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

    msg_ids: dict[str, str] = {}
    for msg in model.messages:
        eid = entity_id("proto_message", "grpc", msg.name)
        msg_ids[msg.name] = eid
        graph.add_entity(Entity(id=eid, kind="proto_message", name=msg.name))

    for svc in model.services:
        sid = entity_id("grpc_service", "grpc", f"{svc.package}.{svc.name}")
        graph.add_entity(
            Entity(id=sid, kind="grpc_service", name=f"{svc.package}.{svc.name}")
        )
        link(RelationshipKind.EXPOSES, service_id, sid, svc.location)
        for rpc in svc.methods:
            mid = entity_id(
                "grpc_method", "grpc", f"{svc.package}.{svc.name}/{rpc.name}"
            )
            graph.add_entity(
                Entity(
                    id=mid,
                    kind="grpc_method",
                    name=f"{svc.name}.{rpc.name}",
                    attributes={"streaming": rpc.streaming.value},
                )
            )
            link(RelationshipKind.EXPOSES, sid, mid, rpc.location)
            for tname, rel in (
                (rpc.request_type, RelationshipKind.ACCEPTS),
                (rpc.response_type, RelationshipKind.RETURNS),
            ):
                short = tname.rsplit(".", 1)[-1]
                target = msg_ids.get(tname) or msg_ids.get(short)
                if target:
                    link(rel, mid, target, rpc.location)
    return graph
