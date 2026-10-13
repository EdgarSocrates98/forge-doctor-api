from __future__ import annotations

import json
import random
from typing import Any

import pytest

from forge_doctor_api.core.graph import (
    GRAPH_SCHEMA_VERSION,
    Direction,
    GraphError,
    ServiceGraph,
    ServiceTopology,
)
from forge_doctor_api.core.models import (
    Confidence,
    Entity,
    EntityKind,
    Evidence,
    EvidenceKind,
    ModelError,
    Relationship,
    RelationshipKind,
    UnknownFact,
    entity_id,
    parse_entity_id,
)

EV = Evidence(kind=EvidenceKind.STATIC, source="src/orders/client.py", summary="httpx call", line=3)

MOBILE = "client:mobile:app"
GATEWAY = "gateway:kong:api-gateway"
ORDERS = "service:python:orders-api"
PAYMENTS = "service:python:payments"
INVENTORY = "service:python:inventory"
ENDPOINT = "endpoint:http:GET:/payments/{id}"
DB = "database:postgres:payments"


def ent(raw_id: str, **attrs: str) -> Entity:
    kind, _, identifier = parse_entity_id(raw_id)
    return Entity(id=raw_id, kind=kind, name=identifier, attributes=attrs)


def rel(
    kind: str,
    source: str,
    target: str,
    confidence: Confidence = Confidence.HIGH,
    **extra: Any,
) -> Relationship:
    return Relationship(
        kind=kind,
        source_id=source,
        target_id=target,
        confidence=confidence,
        evidence=(EV,),
        **extra,
    )


ENTITIES = [ent(i) for i in (MOBILE, GATEWAY, ORDERS, PAYMENTS, INVENTORY, ENDPOINT, DB)]
RELATIONSHIPS = [
    rel("CALLS", MOBILE, GATEWAY),
    rel("ROUTES_TO", GATEWAY, ORDERS),
    rel("CALLS", GATEWAY, ORDERS),
    rel("CALLS", ORDERS, PAYMENTS),
    rel("DEPENDS_ON", ORDERS, INVENTORY),
    rel("EXPOSES", PAYMENTS, ENDPOINT),
    rel("WRITES", PAYMENTS, DB),
]


def build(seed: int | None = None) -> ServiceGraph:
    entities, relationships = list(ENTITIES), list(RELATIONSHIPS)
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(entities)
        rng.shuffle(relationships)
    return ServiceGraph(entities, relationships)


def ids(entities: tuple[Entity, ...]) -> list[str]:
    return [e.id for e in entities]


# --- vocabulary (§8.1, §8.2) -------------------------------------------------


def test_entity_kinds_cover_spec() -> None:
    spec = [
        "Service",
        "API",
        "Endpoint",
        "Operation",
        "Schema",
        "Message",
        "Event",
        "Topic",
        "Queue",
        "Subscription",
        "Client",
        "Gateway",
        "LoadBalancer",
        "IdentityProvider",
        "Credential",
        "Deployment",
        "Runtime",
        "Database",
        "Cache",
        "ExternalAPI",
        "Webhook",
        "GraphQLType",
        "GraphQLResolver",
        "GrpcService",
        "GrpcMethod",
        "ProtoMessage",
        "AsyncChannel",
        "Policy",
        "SLO",
    ]
    assert len(EntityKind) == len(spec) == 29
    expected = {
        "service", "api", "endpoint", "operation", "schema", "message", "event", "topic",
        "queue", "subscription", "client", "gateway", "load_balancer", "identity_provider",
        "credential", "deployment", "runtime", "database", "cache", "external_api", "webhook",
        "graphql_type", "graphql_resolver", "grpc_service", "grpc_method", "proto_message",
        "async_channel", "policy", "slo",
    }  # fmt: skip
    assert {k.value for k in EntityKind} == expected


def test_relationship_kinds_cover_spec() -> None:
    spec = [
        "EXPOSES",
        "CALLS",
        "ROUTES_TO",
        "IMPLEMENTS",
        "CONSUMES",
        "PRODUCES",
        "PUBLISHES",
        "SUBSCRIBES",
        "READS",
        "WRITES",
        "AUTHENTICATES_WITH",
        "AUTHORIZED_BY",
        "DEPENDS_ON",
        "USES",
        "RETURNS",
        "ACCEPTS",
        "GOVERNS",
        "DEPLOYED_AS",
        "FRONTED_BY",
        "RETRIES",
        "FALLS_BACK_TO",
    ]
    assert [k.value for k in RelationshipKind] == spec


@pytest.mark.parametrize(
    "raw",
    [
        "service:python:payments",
        "api:openapi:payments-v1",
        "endpoint:http:GET:/payments/{id}",
        "operation:openapi:getPayment",
        "grpc_method:grpc:Payments/GetPayment",
    ],
)
def test_spec_examples_are_canonical(raw: str) -> None:
    kind, domain, identifier = parse_entity_id(raw)
    assert entity_id(kind, domain, identifier) == raw
    assert Entity(id=raw, kind=kind, name=identifier).id == raw


def test_entity_accepts_enum_kind_and_stores_plain_string() -> None:
    entity = Entity(id=PAYMENTS, kind=EntityKind.SERVICE, name="payments")
    assert type(entity.kind) is str
    assert entity == ent(PAYMENTS)


def test_extension_kinds_survive_serialization() -> None:
    custom = Entity(id="feature_flag:launchdarkly:new-checkout", kind="feature_flag", name="f")
    graph = ServiceGraph([ent(ORDERS), custom])
    graph.add_relationship(rel("GATED_BY", ORDERS, custom.id))
    rebuilt = ServiceGraph.from_json(graph.to_json())
    assert rebuilt == graph
    assert ids(rebuilt.neighbors(ORDERS, "GATED_BY")) == [custom.id]


# --- canonical identity (§9) -------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "payments",
        "service:python",
        "service::payments",
        ":python:payments",
        "service:python: payments",
        "service:python:payments ",
        "Service:python:payments",
        "service:Python:payments",
        "service:py thon:payments",
        "service-x:python:payments",
        "service:python:pay\nments",
        "",
    ],
)
def test_non_canonical_ids_rejected(raw: str) -> None:
    with pytest.raises(ModelError):
        parse_entity_id(raw)
    with pytest.raises(ModelError):
        Entity(id=raw, kind="service", name="payments")


@pytest.mark.parametrize(
    "build_rel",
    [
        lambda: rel("CALLS", "payments", PAYMENTS),
        lambda: rel("CALLS", PAYMENTS, "service:python"),
        lambda: rel("calls", ORDERS, PAYMENTS),
        lambda: rel("CALLS ", ORDERS, PAYMENTS),
        lambda: Relationship(
            kind="CALLS", source_id=ORDERS, target_id=PAYMENTS, confidence=Confidence.HIGH
        ),
        lambda: rel("CALLS", ORDERS, PAYMENTS, confidence="HIGH"),
        lambda: rel("CALLS", ORDERS, PAYMENTS, confidence=Confidence.UNKNOWN),
    ],
)
def test_invalid_relationships_rejected(build_rel: Any) -> None:
    with pytest.raises(ModelError):
        build_rel()


def test_distinct_ids_never_merge() -> None:
    graph = ServiceGraph()
    for raw in (PAYMENTS, "service:python:Payments", "service:go:payments", "api:python:payments"):
        graph.add_entity(ent(raw))
    assert len(graph) == 4


def test_duplicate_entity_add_is_idempotent() -> None:
    graph = ServiceGraph()
    first = graph.add_entity(ent(PAYMENTS, team="core"))
    second = graph.add_entity(ent(PAYMENTS, team="core"))
    assert first is second
    assert graph.entities() == (first,)


def test_conflicting_entity_rejected_not_merged() -> None:
    graph = ServiceGraph([ent(PAYMENTS, team="core")])
    with pytest.raises(GraphError, match="conflicting"):
        graph.add_entity(ent(PAYMENTS, team="other"))
    assert graph.get(PAYMENTS) == ent(PAYMENTS, team="core")


def test_duplicate_relationship_add_is_idempotent_and_conflict_rejected() -> None:
    graph = build()
    before = graph.to_json()
    graph.add_relationship(rel("CALLS", ORDERS, PAYMENTS))
    assert graph.to_json() == before
    with pytest.raises(GraphError, match="conflicting"):
        graph.add_relationship(rel("CALLS", ORDERS, PAYMENTS, confidence=Confidence.LOW))


def test_dangling_relationship_rejected() -> None:
    graph = ServiceGraph([ent(ORDERS)])
    with pytest.raises(GraphError, match="unknown entity"):
        graph.add_relationship(rel("CALLS", ORDERS, PAYMENTS))
    assert graph.relationships() == ()


def test_wrong_types_rejected() -> None:
    graph = ServiceGraph()
    with pytest.raises(GraphError):
        graph.add_entity(PAYMENTS)  # type: ignore[arg-type]
    with pytest.raises(GraphError):
        graph.add_relationship(ent(PAYMENTS))  # type: ignore[arg-type]


# --- queries -----------------------------------------------------------------


def test_get_by_id() -> None:
    graph = build()
    assert graph.get(PAYMENTS) == ent(PAYMENTS)
    assert graph.get("service:python:missing") is None
    assert PAYMENTS in graph
    assert "service:python:missing" not in graph


def test_list_by_kind_sorted() -> None:
    graph = build()
    assert ids(graph.entities(EntityKind.SERVICE)) == [INVENTORY, ORDERS, PAYMENTS]
    assert ids(graph.entities("client")) == [MOBILE]
    assert graph.entities("webhook") == ()
    assert ids(graph.entities()) == sorted(e.id for e in ENTITIES)


def test_relationships_by_kind_sorted() -> None:
    graph = build()
    calls = graph.relationships(RelationshipKind.CALLS)
    assert [(r.source_id, r.target_id) for r in calls] == [
        (MOBILE, GATEWAY),
        (GATEWAY, ORDERS),
        (ORDERS, PAYMENTS),
    ]


def test_neighbors_by_relationship_kind_and_direction() -> None:
    graph = build()
    assert ids(graph.neighbors(ORDERS)) == [INVENTORY, PAYMENTS]
    assert ids(graph.neighbors(ORDERS, RelationshipKind.CALLS)) == [PAYMENTS]
    assert ids(graph.neighbors(ORDERS, "DEPENDS_ON")) == [INVENTORY]
    assert ids(graph.neighbors(ORDERS, direction=Direction.IN)) == [GATEWAY]
    assert ids(graph.neighbors(ORDERS, direction=Direction.BOTH)) == [GATEWAY, INVENTORY, PAYMENTS]
    assert graph.neighbors(DB) == ()
    assert [r.kind for r in graph.edges(GATEWAY, direction=Direction.OUT)] == ["CALLS", "ROUTES_TO"]


def test_parallel_edges_of_different_kinds_yield_one_neighbor() -> None:
    graph = build()
    assert ids(graph.neighbors(GATEWAY)) == [ORDERS]


def test_queries_on_unknown_entity_raise() -> None:
    graph = build()
    with pytest.raises(GraphError, match="unknown entity"):
        graph.neighbors("service:python:missing")
    with pytest.raises(GraphError, match="unknown entity"):
        graph.reachable("service:python:missing")


def test_reachable_transitive_and_kind_filtered() -> None:
    graph = build()
    assert ids(graph.reachable(MOBILE, ["CALLS"])) == [GATEWAY, ORDERS, PAYMENTS]
    assert ids(graph.reachable(MOBILE)) == sorted(
        [DB, ENDPOINT, GATEWAY, INVENTORY, ORDERS, PAYMENTS]
    )
    assert ids(graph.reachable(DB, direction=Direction.IN)) == sorted(
        [PAYMENTS, ORDERS, GATEWAY, MOBILE]
    )


def test_cycle_does_not_break_traversal() -> None:
    graph = build()
    graph.add_relationship(rel("CALLS", PAYMENTS, ORDERS))
    graph.add_relationship(rel("RETRIES", PAYMENTS, PAYMENTS))
    assert ids(graph.reachable(ORDERS, ["CALLS"])) == [ORDERS, PAYMENTS]
    assert ids(graph.reachable(PAYMENTS, ["RETRIES"])) == [PAYMENTS]
    assert ids(graph.neighbors(PAYMENTS, "RETRIES")) == [PAYMENTS]
    assert ids(graph.reachable(INVENTORY, direction=Direction.BOTH)) == sorted(
        e.id for e in ENTITIES
    )
    topology = graph.topology()
    assert topology.dependencies_of(PAYMENTS) == (ORDERS,)
    assert ServiceGraph.from_json(graph.to_json()) == graph


# --- uncertainty (§1 UNKNOWN semantics) ---------------------------------------


def test_uncertain_relationship_representable() -> None:
    gap = UnknownFact(
        subject=f"{ORDERS} -> {PAYMENTS}",
        missing="base URL resolved from environment at runtime",
        resolution="provide deployment env config",
    )
    uncertain = rel("CALLS", ORDERS, PAYMENTS, confidence=Confidence.UNKNOWN, unknowns=(gap,))
    graph = ServiceGraph([ent(ORDERS), ent(PAYMENTS)], [uncertain])
    stored = graph.relationships()[0]
    assert stored.confidence is Confidence.UNKNOWN
    assert stored.unknowns == (gap,)
    data = json.loads(graph.to_json())["relationships"][0]
    assert data["confidence"] == "UNKNOWN"
    assert data["unknowns"][0]["missing"] == gap.missing
    assert ServiceGraph.from_json(graph.to_json()) == graph


# --- topology (§58) ------------------------------------------------------------


def test_topology_service_level_adjacency() -> None:
    topology = build().topology()
    assert topology.services == (MOBILE, GATEWAY, INVENTORY, ORDERS, PAYMENTS)
    assert topology.dependencies == {
        MOBILE: (GATEWAY,),
        GATEWAY: (ORDERS,),
        INVENTORY: (),
        ORDERS: (INVENTORY, PAYMENTS),
        PAYMENTS: (),
    }
    assert topology.dependents_of(ORDERS) == (GATEWAY,)
    assert topology.dependencies_of("service:python:missing") == ()


def test_topology_ignores_non_service_and_non_dependency_edges() -> None:
    graph = ServiceGraph(
        [ent(ORDERS), ent(PAYMENTS), ent(ENDPOINT), ent("endpoint:http:POST:/orders")],
        [
            rel("CALLS", "endpoint:http:POST:/orders", ENDPOINT),
            rel("USES", ORDERS, PAYMENTS),
        ],
    )
    topology = graph.topology()
    assert topology.dependencies == {ORDERS: (), PAYMENTS: ()}


def test_topology_round_trip_and_validation() -> None:
    topology = build().topology()
    assert ServiceTopology.from_json(topology.to_json()) == topology
    with pytest.raises(ModelError):
        ServiceTopology(services=(PAYMENTS, ORDERS), dependencies={ORDERS: (), PAYMENTS: ()})
    with pytest.raises(ModelError):
        ServiceTopology(services=(ORDERS,), dependencies={ORDERS: (PAYMENTS,)})
    with pytest.raises(ModelError):
        ServiceTopology(services=(ORDERS,), dependencies={})
    with pytest.raises(ModelError):
        ServiceTopology(services=("orders",), dependencies={"orders": ()})


# --- serialization & determinism ------------------------------------------------


def test_serialization_round_trip() -> None:
    graph = build()
    data = graph.to_dict()
    assert data["schema_version"] == GRAPH_SCHEMA_VERSION
    assert ServiceGraph.from_dict(data) == graph
    assert ServiceGraph.from_json(graph.to_json()).to_json() == graph.to_json()


@pytest.mark.parametrize("seed", range(10))
def test_insertion_order_never_leaks(seed: int) -> None:
    graph = build(seed)
    reference = build()
    assert graph.to_json() == reference.to_json()
    assert graph.topology().to_json() == reference.topology().to_json()
    assert ids(graph.reachable(MOBILE)) == ids(reference.reachable(MOBILE))
    for entity in ENTITIES:
        both = Direction.BOTH
        assert graph.edges(entity.id, direction=both) == reference.edges(entity.id, direction=both)


def test_serialized_output_sorted_at_every_level() -> None:
    data = json.loads(build(seed=3).to_json())
    assert [e["id"] for e in data["entities"]] == sorted(e["id"] for e in data["entities"])
    keys = [(r["source_id"], r["kind"], r["target_id"]) for r in data["relationships"]]
    assert keys == sorted(keys)

    def check(node: object) -> None:
        if isinstance(node, dict):
            assert list(node) == sorted(node)
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(data)


def test_serialized_graph_is_redacted() -> None:
    graph = ServiceGraph([ent(PAYMENTS, api_key="sk-live-raw-secret")])
    assert "sk-live-raw-secret" not in graph.to_json()


# --- malformed ---------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "graph",
        {"entities": [], "relationships": []},
        {"entities": [], "relationships": [], "schema_version": "2.0"},
        {"entities": [], "relationships": [], "schema_version": 1},
        {"entities": {}, "relationships": [], "schema_version": "1.0"},
        {"entities": [], "relationships": [], "schema_version": "1.0", "extra": 1},
        {"entities": [{"id": "payments"}], "relationships": [], "schema_version": "1.0"},
        {
            "entities": [{"id": PAYMENTS, "kind": "service", "name": "p", "attributes": {}}],
            "relationships": [
                {
                    "kind": "CALLS",
                    "source_id": PAYMENTS,
                    "target_id": ORDERS,
                    "confidence": "HIGH",
                    "evidence": [EV.to_dict()],
                    "unknowns": [],
                }
            ],
            "schema_version": "1.0",
        },
        {
            "entities": [
                {"id": PAYMENTS, "kind": "service", "name": "p", "attributes": {}},
                {"id": PAYMENTS, "kind": "service", "name": "q", "attributes": {}},
            ],
            "relationships": [],
            "schema_version": "1.0",
        },
    ],
)
def test_malformed_graph_payload_rejected(payload: object) -> None:
    with pytest.raises(ModelError):
        ServiceGraph.from_dict(payload)


def test_malformed_graph_json_rejected() -> None:
    with pytest.raises(GraphError, match="malformed JSON"):
        ServiceGraph.from_json("{nope")


def test_relationship_without_evidence_rejected_on_decode() -> None:
    data = rel("CALLS", ORDERS, PAYMENTS).to_dict()
    data["evidence"] = []
    with pytest.raises(ModelError, match="evidence"):
        Relationship.from_dict(data)
