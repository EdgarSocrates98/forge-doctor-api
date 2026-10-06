"""`ApiClientModel` -> ServiceGraph (§8, §15, §17).

- `client:{name}` — one entity per distinct consuming identity.
- `client -[CONSUMES]-> endpoint:http:{METHOD} {path}` per literal call site.

Edges carry the call site as STATIC evidence; unresolvable call sites
produce entities only for the client, never guessed edges.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.clients.model import ApiClientModel
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


def client_graph(model: ApiClientModel) -> ServiceGraph:
    graph = ServiceGraph()
    for client in model.clients:
        client_id = entity_id(EntityKind.CLIENT, "source", client)
        graph.add_entity(Entity(id=client_id, kind=EntityKind.CLIENT, name=client))
    for site in model.call_sites:
        if site.method is None or site.path is None:
            continue
        client_id = entity_id(EntityKind.CLIENT, "source", site.client)
        endpoint_id = entity_id(
            EntityKind.ENDPOINT, "http", f"{site.method} {site.path}"
        )
        graph.add_entity(
            Entity(id=endpoint_id, kind=EntityKind.ENDPOINT, name=f"{site.method} {site.path}")
        )
        graph.add_relationship(
            Relationship(
                kind=RelationshipKind.CONSUMES,
                source_id=client_id,
                target_id=endpoint_id,
                confidence=Confidence.HIGH,
                evidence=(
                    Evidence(
                        kind=EvidenceKind.STATIC,
                        source=site.location.path,
                        summary=f"{site.library} call at line {site.location.line}",
                        line=site.location.line,
                    ),
                ),
            )
        )
    return graph
