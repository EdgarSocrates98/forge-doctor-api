"""RouteScan -> ServiceGraph (§8, §15).

- `service:python:{name}` — the scanned service.
- `endpoint:http:{METHOD} {path}` — one per route surface.
- `operation:{framework}:{handler}` — the implementing handler.

Edges (each carrying the decorator/call site as STATIC evidence):

```text
service  -[EXPOSES]->   endpoint
operation -[IMPLEMENTS]-> endpoint
```

Edges are never inferred; dedupe is by identity via `ServiceGraph` itself.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.routes.model import RouteScan
from forge_doctor_api.core.graph import ServiceGraph
from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    EntityKind,
    Evidence,
    EvidenceKind,
    Relationship,
    RelationshipKind,
    entity_id,
)


def scan_graph(scan: RouteScan) -> ServiceGraph:
    graph = ServiceGraph()
    service_id = entity_id(EntityKind.SERVICE, "python", scan.service)
    graph.add_entity(Entity(id=service_id, kind=EntityKind.SERVICE, name=scan.service))
    for route in scan.routes:
        endpoint_id = entity_id(EntityKind.ENDPOINT, "http", f"{route.method} {route.path}")
        operation_id = entity_id("operation", route.framework, route.handler)
        evidence = (
            Evidence(
                kind=EvidenceKind.STATIC,
                source=route.source_location.path,
                summary=f"{route.method} {route.path} -> {route.handler}",
                line=route.source_location.line,
            ),
        )
        graph.add_entity(
            Entity(
                id=endpoint_id,
                kind=EntityKind.ENDPOINT,
                name=f"{route.method} {route.path}",
                attributes={"method": route.method, "path": route.path},
            )
        )
        graph.add_entity(
            Entity(
                id=operation_id,
                kind=EntityKind.OPERATION,
                name=route.handler,
                attributes={"framework": route.framework, "service": route.service},
            )
        )
        graph.add_relationship(
            Relationship(
                kind=RelationshipKind.EXPOSES,
                source_id=service_id,
                target_id=endpoint_id,
                confidence=Confidence.HIGH,
                evidence=evidence,
            )
        )
        graph.add_relationship(
            Relationship(
                kind=RelationshipKind.IMPLEMENTS,
                source_id=operation_id,
                target_id=endpoint_id,
                confidence=Confidence.HIGH,
                evidence=evidence,
            )
        )
    return graph
