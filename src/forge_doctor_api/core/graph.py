"""ServiceGraph: the in-memory entity/relationship graph (§8, §9, §58).

Identity is canonical and exact: an entity is its `{kind}:{domain}:{identifier}`
id and nothing else. Re-adding an identical entity or edge is a no-op;
re-adding the same id or edge key with different content is a `GraphError`,
never a merge. There is no similarity matching, name-based linking, or edge
inference — only edges an analyzer recorded with evidence. Every query and
the serialized form are sorted, so insertion order never leaks.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from forge_doctor_api.core.models import (
    Entity,
    EntityKind,
    Model,
    ModelError,
    Relationship,
    RelationshipKind,
    parse_entity_id,
)

GRAPH_SCHEMA_VERSION = "1.0"

# Node kinds that appear as boxes in a §58 service dependency diagram.
SERVICE_LEVEL_KINDS: frozenset[str] = frozenset(
    {EntityKind.SERVICE, EntityKind.CLIENT, EntityKind.GATEWAY, EntityKind.EXTERNAL_API}
)
TOPOLOGY_RELATIONSHIPS: frozenset[str] = frozenset(
    {RelationshipKind.CALLS, RelationshipKind.DEPENDS_ON}
)


class GraphError(ModelError):
    """Raised on identity conflicts, dangling edges, or unknown entity ids."""


class Direction(StrEnum):
    OUT = "OUT"
    IN = "IN"
    BOTH = "BOTH"


@dataclass(frozen=True, kw_only=True)
class ServiceTopology(Model):
    """Service-level dependency adjacency (§58): who CALLS / DEPENDS_ON whom.

    `services` lists every service-level node (sorted); `dependencies` maps
    each of them to its sorted, de-duplicated direct targets. Built only from
    explicitly recorded service-level edges; endpoint-level calls are not
    rolled up, since that would be inference.
    """

    services: tuple[str, ...] = ()
    dependencies: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for service in self.services:
            parse_entity_id(service)
        if list(self.services) != sorted(set(self.services)):
            raise ModelError("ServiceTopology.services must be sorted and unique")
        known = set(self.services)
        if set(self.dependencies) != known:
            raise ModelError("ServiceTopology.dependencies must have one entry per service")
        for source, targets in self.dependencies.items():
            if list(targets) != sorted(set(targets)):
                raise ModelError(f"ServiceTopology targets of {source!r} must be sorted, unique")
            if not set(targets) <= known:
                raise ModelError(f"ServiceTopology targets of {source!r} must be services")

    def dependencies_of(self, service_id: str) -> tuple[str, ...]:
        return self.dependencies.get(service_id, ())

    def dependents_of(self, service_id: str) -> tuple[str, ...]:
        return tuple(s for s in self.services if service_id in self.dependencies[s])


class ServiceGraph:
    """Mutable in-memory graph with deterministic queries and serialization."""

    def __init__(
        self,
        entities: Iterable[Entity] = (),
        relationships: Iterable[Relationship] = (),
    ) -> None:
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[tuple[str, str, str], Relationship] = {}
        self._out: dict[str, dict[tuple[str, str, str], Relationship]] = {}
        self._in: dict[str, dict[tuple[str, str, str], Relationship]] = {}
        for entity in entities:
            self.add_entity(entity)
        for relationship in relationships:
            self.add_relationship(relationship)

    # --- mutation -----------------------------------------------------------

    def add_entity(self, entity: Entity) -> Entity:
        if not isinstance(entity, Entity):
            raise GraphError(f"expected an Entity, got {type(entity).__name__}")
        existing = self._entities.get(entity.id)
        if existing is not None:
            if existing != entity:
                raise GraphError(f"conflicting definitions for entity {entity.id!r}")
            return existing
        self._entities[entity.id] = entity
        self._out[entity.id] = {}
        self._in[entity.id] = {}
        return entity

    def add_relationship(self, relationship: Relationship) -> Relationship:
        if not isinstance(relationship, Relationship):
            raise GraphError(f"expected a Relationship, got {type(relationship).__name__}")
        for end in (relationship.source_id, relationship.target_id):
            if end not in self._entities:
                raise GraphError(f"relationship references unknown entity {end!r}")
        key = relationship.key
        existing = self._relationships.get(key)
        if existing is not None:
            if existing != relationship:
                raise GraphError(f"conflicting definitions for relationship {key!r}")
            return existing
        self._relationships[key] = relationship
        self._out[relationship.source_id][key] = relationship
        self._in[relationship.target_id][key] = relationship
        return relationship

    # --- queries ------------------------------------------------------------

    def __contains__(self, entity_id: object) -> bool:
        return entity_id in self._entities

    def __len__(self) -> int:
        return len(self._entities)

    def get(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def entities(self, kind: str | None = None) -> tuple[Entity, ...]:
        return tuple(
            self._entities[eid]
            for eid in sorted(self._entities)
            if kind is None or self._entities[eid].kind == kind
        )

    def relationships(self, kind: str | None = None) -> tuple[Relationship, ...]:
        return tuple(
            self._relationships[key]
            for key in sorted(self._relationships)
            if kind is None or key[1] == kind
        )

    def edges(
        self,
        entity_id: str,
        kind: str | None = None,
        direction: Direction = Direction.OUT,
    ) -> tuple[Relationship, ...]:
        """Relationships touching `entity_id`, sorted by `(source, kind, target)`."""
        self._require(entity_id)
        found: dict[tuple[str, str, str], Relationship] = {}
        if direction in (Direction.OUT, Direction.BOTH):
            found.update(self._out[entity_id])
        if direction in (Direction.IN, Direction.BOTH):
            found.update(self._in[entity_id])
        return tuple(found[key] for key in sorted(found) if kind is None or key[1] == kind)

    def neighbors(
        self,
        entity_id: str,
        kind: str | None = None,
        direction: Direction = Direction.OUT,
    ) -> tuple[Entity, ...]:
        """Adjacent entities via `kind` edges (all kinds if None), sorted by id."""
        ids: set[str] = set()
        for rel in self.edges(entity_id, kind, direction):
            if direction in (Direction.OUT, Direction.BOTH) and rel.source_id == entity_id:
                ids.add(rel.target_id)
            if direction in (Direction.IN, Direction.BOTH) and rel.target_id == entity_id:
                ids.add(rel.source_id)
        return tuple(self._entities[eid] for eid in sorted(ids))

    def reachable(
        self,
        entity_id: str,
        kinds: Iterable[str] | None = None,
        direction: Direction = Direction.OUT,
    ) -> tuple[Entity, ...]:
        """Entities transitively reachable from `entity_id`, sorted by id.

        Cycle-safe: each entity is visited once. The start entity is included
        only if a cycle leads back to it.
        """
        self._require(entity_id)
        allowed = None if kinds is None else {str(k) for k in kinds}
        seen: set[str] = set()
        frontier = [entity_id]
        while frontier:
            current = frontier.pop()
            for neighbor in self._step(current, allowed, direction):
                if neighbor not in seen:
                    seen.add(neighbor)
                    frontier.append(neighbor)
        return tuple(self._entities[eid] for eid in sorted(seen))

    def topology(self) -> ServiceTopology:
        services = tuple(e.id for e in self.entities() if e.kind in SERVICE_LEVEL_KINDS)
        members = set(services)
        adjacency: dict[str, set[str]] = {s: set() for s in services}
        for rel in self._relationships.values():
            if (
                rel.kind in TOPOLOGY_RELATIONSHIPS
                and rel.source_id in members
                and rel.target_id in members
            ):
                adjacency[rel.source_id].add(rel.target_id)
        return ServiceTopology(
            services=services,
            dependencies={s: tuple(sorted(adjacency[s])) for s in services},
        )

    # --- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities()],
            "relationships": [r.to_dict() for r in self.relationships()],
            "schema_version": GRAPH_SCHEMA_VERSION,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, data: Any) -> ServiceGraph:
        if not isinstance(data, Mapping):
            raise GraphError(f"ServiceGraph: expected an object, got {type(data).__name__}")
        expected = {"entities", "relationships", "schema_version"}
        if set(data) != expected:
            raise GraphError(f"ServiceGraph: expected keys {sorted(expected)}")
        version = data["schema_version"]
        if not isinstance(version, str) or version.split(".")[0] != "1":
            raise GraphError(f"ServiceGraph: unsupported schema_version {version!r}")
        for name in ("entities", "relationships"):
            if not isinstance(data[name], list):
                raise GraphError(f"ServiceGraph.{name}: expected a list")
        return cls(
            entities=[Entity.from_dict(item) for item in data["entities"]],
            relationships=[Relationship.from_dict(item) for item in data["relationships"]],
        )

    @classmethod
    def from_json(cls, text: str) -> ServiceGraph:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GraphError(f"ServiceGraph: malformed JSON: {exc.msg}") from exc
        return cls.from_dict(data)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ServiceGraph):
            return NotImplemented
        return self._entities == other._entities and self._relationships == other._relationships

    __hash__ = None  # type: ignore[assignment]

    # --- internals ----------------------------------------------------------

    def _require(self, entity_id: str) -> None:
        if entity_id not in self._entities:
            raise GraphError(f"unknown entity {entity_id!r}")

    def _step(self, current: str, allowed: set[str] | None, direction: Direction) -> list[str]:
        out: list[str] = []
        if direction in (Direction.OUT, Direction.BOTH):
            out += [r.target_id for r in self._out[current].values() if _ok(r, allowed)]
        if direction in (Direction.IN, Direction.BOTH):
            out += [r.source_id for r in self._in[current].values() if _ok(r, allowed)]
        return sorted(out)


def _ok(relationship: Relationship, allowed: set[str] | None) -> bool:
    return allowed is None or relationship.kind in allowed
