"""`AsyncApiProjectModel` -> ServiceGraph (§20.2).

```text
service   -[PUBLISHES]->  async_channel   (send-side operations)
service   -[SUBSCRIBES]-> async_channel   (receive-side operations)
operation -[PRODUCES]->   message         (send-side)
operation -[CONSUMES]->   message         (receive-side)
```

Every edge carries the declaring node as STATIC evidence.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.asyncapi.model import (
    AsyncAction,
    AsyncApiProjectModel,
)
from forge_doctor_api.core.graph import ServiceGraph
from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    EntityKind,
    Evidence,
    EvidenceKind,
    Relationship,
    RelationshipKind,
    SourceLocation,
    entity_id,
)


def async_graph(model: AsyncApiProjectModel, service: str) -> ServiceGraph:
    graph = ServiceGraph()
    service_id = entity_id(EntityKind.SERVICE, "asyncapi", service)
    graph.add_entity(Entity(id=service_id, kind=EntityKind.SERVICE, name=service))

    channels = {c.pointer: c for c in model.channels}
    channel_entity = {
        c.pointer: entity_id(
            EntityKind.ASYNC_CHANNEL, "asyncapi",
            f"{c.location.path}#{c.name}")
        for c in model.channels
    }
    for channel in model.channels:
        graph.add_entity(
            Entity(
                id=channel_entity[channel.pointer],
                kind=EntityKind.ASYNC_CHANNEL,
                name=channel.name,
            )
        )
    message_entity = {
        m.pointer: entity_id(
            EntityKind.MESSAGE, "asyncapi",
            f"{m.location.path}#{m.name or m.pointer}")
        for m in model.messages
    }
    for message in model.messages:
        graph.add_entity(
            Entity(
                id=message_entity[message.pointer],
                kind=EntityKind.MESSAGE,
                name=message.name or message.pointer,
            )
        )

    def link(
        kind: RelationshipKind, source: str, target: str, loc: SourceLocation
    ) -> None:
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

    for op in model.operations:
        op_id = entity_id("operation", "asyncapi", f"{op.action}:{op.name}")
        graph.add_entity(
            Entity(id=op_id, kind=EntityKind.OPERATION, name=op.name)
        )
        if op.channel_pointer and op.channel_pointer in channel_entity:
            link(
                RelationshipKind.PUBLISHES
                if op.action is AsyncAction.SEND
                else RelationshipKind.SUBSCRIBES,
                service_id,
                channel_entity[op.channel_pointer],
                op.location,
            )
        bound_channel = channels.get(op.channel_pointer or "")
        msg_ptrs = op.message_pointers or (
            bound_channel.message_pointers if bound_channel else ()
        )
        for ptr in msg_ptrs:
            if ptr in message_entity:
                link(
                    RelationshipKind.PRODUCES
                    if op.action is AsyncAction.SEND
                    else RelationshipKind.CONSUMES,
                    op_id,
                    message_entity[ptr],
                    op.location,
                )
    return graph
