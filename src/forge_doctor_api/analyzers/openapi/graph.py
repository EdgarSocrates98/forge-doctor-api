"""API contract graph (§15): OpenAPI model -> ServiceGraph.

```text
api        -[EXPOSES]-> operation
operation  -[ACCEPTS]-> schema     (request body $ref targets)
operation  -[RETURNS]-> schema     (response $ref targets)
```

Only resolved `ref:` schema shapes become schema edges — inline schemas are
fingerprinted but not entities. Every edge carries its source location as
STATIC evidence; nothing is inferred.
"""

from __future__ import annotations

import re

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
    OperationSource,
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

_REF_SHAPE = re.compile(r"^ref:.*/(?P<name>[^/]+)$")


def _ev(loc: SourceLocation, summary: str) -> tuple[Evidence, ...]:
    return (
        Evidence(
            kind=EvidenceKind.STATIC,
            source=loc.path,
            summary=summary,
            line=loc.line,
        ),
    )


def contract_graph(model: OpenApiProjectModel) -> ServiceGraph:
    graph = ServiceGraph()
    responses = {(r.location.path, r.pointer): r for r in model.responses}
    bodies = {(b.location.path, b.pointer): b for b in model.request_bodies}
    # Schema entity ids are document-qualified (`{doc}#{name}`): two
    # documents may declare a `User` each — unqualified ids collide and
    # name-only edges would bind an operation to the wrong document's
    # declaration. $refs inside a document resolve document-locally.
    declared = {(s.location.path, s.name) for s in model.schemas}
    for schema in model.schemas:
        graph.add_entity(
            Entity(
                id=entity_id(
                    EntityKind.SCHEMA, "openapi",
                    f"{schema.location.path}#{schema.name}"),
                kind=EntityKind.SCHEMA,
                name=schema.name,
                attributes={"document": schema.location.path},
            )
        )

    api_ids: dict[str, str] = {}
    for doc in model.documents:
        api_id = entity_id(EntityKind.API, "openapi", doc.location.path)
        api_ids[doc.location.path] = api_id
        graph.add_entity(
            Entity(
                id=api_id,
                kind=EntityKind.API,
                name=doc.title or doc.location.path,
                attributes={
                    "document": doc.location.path,
                    "openapi_version": doc.openapi_version or "",
                },
            )
        )

    def edge(kind: RelationshipKind, src: str, dst: str, loc: SourceLocation, summary: str) -> None:
        graph.add_relationship(
            Relationship(
                kind=kind,
                source_id=src,
                target_id=dst,
                confidence=Confidence.HIGH,
                evidence=_ev(loc, summary),
            )
        )

    def op_schema_refs(op: OpenApiOperation) -> tuple[tuple[str, ...], tuple[str, ...]]:
        accepts: set[str] = set()
        returns: set[str] = set()
        body = bodies.get((op.location.path, op.request_body_pointer or ""))
        if body is not None:
            for shape in body.schema_shapes:
                match = _REF_SHAPE.match(shape)
                if match and (op.location.path, match["name"]) in declared:
                    accepts.add(match["name"])
        for pointer in op.response_pointers:
            response = responses.get((op.location.path, pointer))
            if response is None:
                continue
            for shape in response.schema_shapes:
                match = _REF_SHAPE.match(shape)
                if match and (op.location.path, match["name"]) in declared:
                    returns.add(match["name"])
        return tuple(sorted(accepts)), tuple(sorted(returns))

    for op in model.operations:
        if op.source is not OperationSource.PATH:
            continue
        operation_id = entity_id(EntityKind.OPERATION, "openapi", op.identity)
        graph.add_entity(
            Entity(
                id=operation_id,
                kind=EntityKind.OPERATION,
                name=op.identity,
                attributes={"method": op.method, "path": op.path},
            )
        )
        edge(
            RelationshipKind.EXPOSES,
            api_ids[op.location.path],
            operation_id,
            op.location,
            f"api exposes {op.method} {op.path}",
        )
        accepts, returns = op_schema_refs(op)
        for name in accepts:
            edge(
                RelationshipKind.ACCEPTS,
                operation_id,
                entity_id(EntityKind.SCHEMA, "openapi",
                          f"{op.location.path}#{name}"),
                op.location,
                f"{op.method} {op.path} accepts {name}",
            )
        for name in returns:
            edge(
                RelationshipKind.RETURNS,
                operation_id,
                entity_id(EntityKind.SCHEMA, "openapi",
                          f"{op.location.path}#{name}"),
                op.location,
                f"{op.method} {op.path} returns {name}",
            )
    return graph
