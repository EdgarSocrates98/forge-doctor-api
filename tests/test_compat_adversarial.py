"""Adversarial compatibility matrix (spec 087, §16, §17, §20-27).

Named cases per protocol, each asserting the expected classification AND
evidence presence — the taxonomy's value is *distinction*, so cases pin
both BREAKING and POTENTIALLY_BREAKING outcomes plus the unknown-first
policy (partial evidence never upgrades to BREAKING).

- OpenAPI: nullable flip, discriminator change, composition reshuffle
  (see test_compat.py for the base matrix: params, required, enum,
  additionalProperties, content-type, security).
- GraphQL: union member remove/add, directive change, field removal,
  arg requiredness, enum removal.
- gRPC: enum renumbering, oneof membership/add, field-number reuse,
  reserved removal, wire type change, streaming flip, rename.
- AsyncAPI: channel removal, action flip, correlation-id change,
  binding change, message payload/schema removal.
- Client impact: Feign, generated OpenAPI clients, gRPC stubs,
  GraphQL documents + gql templates.
- ServiceGraph identity: exact-match only, conflicting ids rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_doctor_api.analyzers.asyncapi import load_asyncapi_project
from forge_doctor_api.analyzers.clients import scan_clients
from forge_doctor_api.analyzers.grpc import load_grpc_project
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.asyncapi import asyncapi_breaking_changes
from forge_doctor_api.checks.compat import CompatibilityClass, diff_models
from forge_doctor_api.checks.grpc import grpc_breaking_changes
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.graph import GraphError, ServiceGraph
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


def _write(root: Path, files: dict[str, str]) -> ProjectContext:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return ProjectContext.from_root(root)


def _oapi(root: Path, files: dict[str, str]):
    return load_openapi_project(_write(root, files), list(files))


def _grpc(root: Path, files: dict[str, str]):
    return load_grpc_project(_write(root, files), list(files))


def _async(root: Path, files: dict[str, str]):
    return load_asyncapi_project(_write(root, files), list(files))


def _classified(changes, cls: CompatibilityClass) -> list[str]:
    return [c.kind for c in changes if c.classification is cls]


def _assert_evidenced(change) -> None:
    """Every classification carries evidence refs — never a bare verdict."""
    assert change.detail
    assert change.location is not None


# ---------------------------------------------------------------------------
# OpenAPI — nullable / discriminator / composition (§16.2-3, §122)
# ---------------------------------------------------------------------------

NULLABLE_BASE = """openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Pet'}
    post:
      operationId: createPet
      requestBody:
        content:
          application/json:
            schema: {$ref: '#/components/schemas/PetIn'}
      responses:
        '201': {description: made}
components:
  schemas:
    Pet:
      type: object
      required: [name]
      properties:
        name: {type: string}
        tag: {type: string}
    PetIn:
      type: object
      required: [name]
      properties:
        name: {type: string}
        nickname: {type: string, nullable: true}
"""


def test_nullable_flip_response_breaks(tmp_path: Path) -> None:
    """Response field losing nullability rejects readers holding null."""
    old = NULLABLE_BASE.replace(
        "        tag: {type: string}\n",
        "        tag: {type: string, nullable: true}\n",
    )
    new = old.replace("{type: string, nullable: true}", "{type: string}")
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": old}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    breaking = _classified(diff.changes, CompatibilityClass.BREAKING)
    assert "type_changed_response" in breaking
    change = next(c for c in diff.changes if c.kind == "type_changed_response")
    _assert_evidenced(change)
    assert change.before == "nullable"


def test_nullable_widen_response_candidate(tmp_path: Path) -> None:
    """Response field gaining nullability widens output — candidate."""
    new = NULLABLE_BASE.replace(
        "        name: {type: string}",
        "        name: {type: string, nullable: true}",
    )
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": NULLABLE_BASE}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    candidates = _classified(diff.changes, CompatibilityClass.POTENTIALLY_BREAKING)
    assert "response_type_widened" in candidates
    assert "type_changed_response" not in _classified(
        diff.changes, CompatibilityClass.BREAKING)


def test_nullable_removed_on_request_breaks(tmp_path: Path) -> None:
    """Request field losing nullability rejects clients sending null."""
    new = NULLABLE_BASE.replace(
        "nickname: {type: string, nullable: true}",
        "nickname: {type: string}",
    )
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": NULLABLE_BASE}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    assert "type_changed_request" in _classified(
        diff.changes, CompatibilityClass.BREAKING)


def test_nullable_added_on_request_is_safe(tmp_path: Path) -> None:
    """Request field gaining nullability widens accepted input — no break."""
    new = NULLABLE_BASE.replace(
        "        name: {type: string}\n      properties:\n        name:",
        "        name: {type: string}\n      properties:\n        name:",
    )
    new = NULLABLE_BASE.replace(
        "        name: {type: string}\n        nickname:",
        "        name: {type: string, nullable: true}\n        nickname:",
    )
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": NULLABLE_BASE}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    assert "type_changed_request" not in _classified(
        diff.changes, CompatibilityClass.BREAKING)


DISC_BASE = """openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Pet'}
components:
  schemas:
    Pet:
      type: object
      discriminator: {propertyName: petType}
      required: [petType]
      properties:
        petType: {type: string}
"""


def test_discriminator_removed_breaks(tmp_path: Path) -> None:
    """Dropping the dispatch key reroutes polymorphic deserialization."""
    new = DISC_BASE.replace("      discriminator: {propertyName: petType}\n", "")
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": DISC_BASE}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    breaking = _classified(diff.changes, CompatibilityClass.BREAKING)
    assert "type_changed_response" in breaking
    _assert_evidenced(next(
        c for c in diff.changes if c.kind == "type_changed_response"))


def test_discriminator_propertyname_change_breaks(tmp_path: Path) -> None:
    new = DISC_BASE.replace("propertyName: petType", "propertyName: kind")
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": DISC_BASE}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    assert "type_changed_response" in _classified(
        diff.changes, CompatibilityClass.BREAKING)


def test_discriminator_added_breaks(tmp_path: Path) -> None:
    old = DISC_BASE.replace("      discriminator: {propertyName: petType}\n", "")
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": old}),
                       _oapi(tmp_path / "n", {"a.yaml": DISC_BASE}))
    assert "type_changed_response" in _classified(
        diff.changes, CompatibilityClass.BREAKING)


def test_discriminator_mapping_change_is_candidate(tmp_path: Path) -> None:
    new = DISC_BASE.replace(
        "discriminator: {propertyName: petType}",
        "discriminator: {propertyName: petType, mapping: {cat: '#/C'}}",
    )
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": DISC_BASE}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    change = next(
        c for c in diff.changes if "discriminator" in c.path)
    assert change.classification is CompatibilityClass.POTENTIALLY_BREAKING
    _assert_evidenced(change)


def test_anyof_reshuffle_is_not_silent(tmp_path: Path) -> None:
    """Branch reorder keeps the same set — set-equal must not emit noise."""
    old = NULLABLE_BASE.replace(
        "        tag: {type: string}",
        "        tag: {anyOf: [{type: string}, {type: integer}]}",
    )
    new = old.replace(
        "{anyOf: [{type: string}, {type: integer}]}",
        "{anyOf: [{type: integer}, {type: string}]}",
    )
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": old}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    assert not _classified(diff.changes, CompatibilityClass.BREAKING)


# ---------------------------------------------------------------------------
# GraphQL — union/directive diffs (spec 087)
# ---------------------------------------------------------------------------

GQL_OLD = """directive @auth on FIELD_DEFINITION | OBJECT

type Query {
  search: [SearchResult!]!
  pet(id: ID!): Pet
}
union SearchResult = Cat | Dog
interface Named { name: String }
type Cat implements Named { name: String, lives: Int }
type Dog implements Named { name: String, breed: String @auth }
type Pet { id: ID! }
enum Species { CAT DOG BIRD }
"""


def _gql(root: Path, text: str):
    graphql = pytest.importorskip("graphql")
    del graphql
    from forge_doctor_api.analyzers.graphql import load_graphql_project
    return load_graphql_project(_write(root, {"s.graphql": text}),
                                ["s.graphql"])


def test_graphql_union_member_removed(tmp_path: Path) -> None:
    from forge_doctor_api.checks.graphql import graphql_breaking_changes
    new = GQL_OLD.replace("union SearchResult = Cat | Dog",
                          "union SearchResult = Cat")
    findings = graphql_breaking_changes(
        _gql(tmp_path / "o", GQL_OLD), _gql(tmp_path / "n", new))
    (f,) = [f for f in findings if f.id == "GQL011"]
    assert f.severity.name == "HIGH"
    assert f.evidence
    assert "Dog" in f.description


def test_graphql_union_member_added_candidate(tmp_path: Path) -> None:
    from forge_doctor_api.checks.graphql import graphql_breaking_changes
    new = GQL_OLD.replace("union SearchResult = Cat | Dog",
                          "union SearchResult = Cat | Dog | Bird")
    new += "type Bird { wings: Int }\n"
    findings = graphql_breaking_changes(
        _gql(tmp_path / "o", GQL_OLD), _gql(tmp_path / "n", new))
    (f,) = [f for f in findings if f.id == "GQL013"]
    assert "Bird" in f.description


def test_graphql_directive_change_candidate(tmp_path: Path) -> None:
    from forge_doctor_api.checks.graphql import graphql_breaking_changes
    new = GQL_OLD.replace("breed: String @auth", "breed: String")
    findings = graphql_breaking_changes(
        _gql(tmp_path / "o", GQL_OLD), _gql(tmp_path / "n", new))
    (f,) = [f for f in findings if f.id == "GQL012"]
    assert "Dog.breed" in f.description


def test_graphql_field_removed_breaks(tmp_path: Path) -> None:
    from forge_doctor_api.checks.graphql import graphql_breaking_changes
    new = GQL_OLD.replace(", lives: Int", "")
    findings = graphql_breaking_changes(
        _gql(tmp_path / "o", GQL_OLD), _gql(tmp_path / "n", new))
    assert "GQL002" in {f.id for f in findings}


def test_graphql_enum_value_removed_breaks(tmp_path: Path) -> None:
    from forge_doctor_api.checks.graphql import graphql_breaking_changes
    new = GQL_OLD.replace("enum Species { CAT DOG BIRD }",
                          "enum Species { CAT DOG }")
    findings = graphql_breaking_changes(
        _gql(tmp_path / "o", GQL_OLD), _gql(tmp_path / "n", new))
    assert "GQL005" in {f.id for f in findings}


# ---------------------------------------------------------------------------
# gRPC — enum renumber + oneof (spec 087)
# ---------------------------------------------------------------------------

GRPC_OLD = '''syntax = "proto3";
package acme.v1;
message Get { string id = 1; }
message Reply {
  string id = 1;
  oneof contact { string phone = 2; string email = 3; }
  string legacy = 4;
}
service Svc { rpc Get(Get) returns (Reply); }
enum Role { ROLE_UNSPECIFIED = 0; ADMIN = 1; USER = 2; }
'''


def test_grpc_enum_renumber_breaks(tmp_path: Path) -> None:
    new = GRPC_OLD.replace("ADMIN = 1", "ADMIN = 7")
    findings = grpc_breaking_changes(
        _grpc(tmp_path / "o", {"a.proto": GRPC_OLD}),
        _grpc(tmp_path / "n", {"a.proto": new})).findings
    (f,) = [f for f in findings if f.id == "GRPC008"]
    assert "ADMIN" in f.description
    assert f.evidence


def test_grpc_oneof_membership_change_breaks(tmp_path: Path) -> None:
    """Moving a field out of a oneof changes exclusivity semantics."""
    new = GRPC_OLD.replace(
        "  oneof contact { string phone = 2; string email = 3; }\n",
        "  string phone = 2;\n  oneof contact { string email = 3; }\n",
    )
    findings = grpc_breaking_changes(
        _grpc(tmp_path / "o", {"a.proto": GRPC_OLD}),
        _grpc(tmp_path / "n", {"a.proto": new})).findings
    (f,) = [f for f in findings if f.id == "GRPC009"]
    assert "phone" in f.description


def test_grpc_oneof_member_added_candidate(tmp_path: Path) -> None:
    new = GRPC_OLD.replace(
        "oneof contact { string phone = 2; string email = 3; }",
        "oneof contact { string phone = 2; string email = 3; "
        "string fax = 5; }",
    )
    findings = grpc_breaking_changes(
        _grpc(tmp_path / "o", {"a.proto": GRPC_OLD}),
        _grpc(tmp_path / "n", {"a.proto": new})).findings
    (f,) = [f for f in findings if f.id == "GRPC009"]
    assert "fax" in f.description


def test_grpc_field_number_reuse_breaks(tmp_path: Path) -> None:
    new = GRPC_OLD.replace(
        "  string legacy = 4;",
        "  int32 count = 4;",
    )
    findings = grpc_breaking_changes(
        _grpc(tmp_path / "o", {"a.proto": GRPC_OLD}),
        _grpc(tmp_path / "n", {"a.proto": new})).findings
    assert "GRPC004" in {f.id for f in findings}


def test_grpc_rename_breaks(tmp_path: Path) -> None:
    """Rename is a recorded breaking *change* — no dedicated catalog id,
    so it surfaces in ContractDiff.changes, not findings."""
    new = GRPC_OLD.replace("package acme.v1;", "package acme.v2;")
    diff = grpc_breaking_changes(
        _grpc(tmp_path / "o", {"a.proto": GRPC_OLD}),
        _grpc(tmp_path / "n", {"a.proto": new}))
    renames = [c for c in diff.changes if c.kind == "GRPC_RENAME"]
    assert renames
    assert all(
        c.classification is CompatibilityClass.BREAKING for c in renames)


# ---------------------------------------------------------------------------
# AsyncAPI — compat diff (spec 087)
# ---------------------------------------------------------------------------

ASYNC_OLD = """asyncapi: "2.6.0"
info: {title: Events, version: "1.0"}
channels:
  user/signedup:
    bindings: {kafka: {partitions: 3}}
    publish:
      operationId: pubSign
      message: {$ref: '#/components/messages/SignedUp'}
components:
  messages:
    SignedUp:
      correlationId: {location: "$message.header#/cid"}
      contentType: application/json
      payload: {$ref: '#/components/schemas/Event'}
      bindings: {kafka: {key: {type: string}}}
  schemas:
    Event:
      type: object
      properties:
        id: {type: string}
"""


def test_async_channel_removed_breaks(tmp_path: Path) -> None:
    new = ASYNC_OLD.replace(
        "  user/signedup:",
        "  user/removed:",
    )
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    kinds = {f.id for f in findings}
    assert "ASYNC009" in kinds   # channel removed
    assert "ASYNC010" in kinds   # channel added (rename = remove+add)


def test_async_action_flip_breaks(tmp_path: Path) -> None:
    new = ASYNC_OLD.replace("    publish:\n", "    subscribe:\n")
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    (f,) = [f for f in findings if f.id == "ASYNC012"]
    assert "send" in f.description and "receive" in f.description


def test_async_correlation_change_breaks(tmp_path: Path) -> None:
    new = ASYNC_OLD.replace(
        '"$message.header#/cid"', '"$message.payload#/cid"')
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    (f,) = [f for f in findings if f.id == "ASYNC013"]
    assert f.evidence


def test_async_binding_change_candidate(tmp_path: Path) -> None:
    """Bindings record protocol names — a channel moving kafka->amqp is a
    POTENTIALLY-breaking protocol rebinding."""
    new = ASYNC_OLD.replace(
        "bindings: {kafka: {partitions: 3}}",
        "bindings: {amqp: {partitions: 3}}",
    )
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    (f,) = [f for f in findings if f.id == "ASYNC017"]
    assert f.confidence is Confidence.MEDIUM


def test_async_message_removed_breaks(tmp_path: Path) -> None:
    """Dropping the declared message (component + all refs) removes its
    payload contract entirely."""
    new = ASYNC_OLD.replace(
        "      message: {$ref: '#/components/messages/SignedUp'}\n", "")
    new = new.replace(
        """  messages:
    SignedUp:
      correlationId: {location: "$message.header#/cid"}
      contentType: application/json
      payload: {$ref: '#/components/schemas/Event'}
      bindings: {kafka: {key: {type: string}}}
""",
        "",
    )
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    assert "ASYNC014" in {f.id for f in findings}


def test_async_dangling_ref_surfaces_as_attribute_loss(tmp_path: Path) -> None:
    """Honest edge: deleting the component while the op still refs it
    leaves a dangling message — correlation/bindings diffs fire, not a
    false 'removed' verdict."""
    new = ASYNC_OLD.replace(
        """  messages:
    SignedUp:
      correlationId: {location: "$message.header#/cid"}
      contentType: application/json
      payload: {$ref: '#/components/schemas/Event'}
      bindings: {kafka: {key: {type: string}}}
""",
        "",
    )
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    assert findings
    assert "ASYNC014" not in {f.id for f in findings}


def test_async_payload_schema_breaks(tmp_path: Path) -> None:
    """Property-level drift inside a stable payload ref surfaces via the
    unified schema diff — not just ref-pointer moves."""
    new = ASYNC_OLD.replace(
        "        id: {type: string}",
        "        id: {type: integer}",
    )
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    (f,) = [f for f in findings if f.id == "ASYNC015"]
    assert f.evidence


def test_async_content_type_candidate(tmp_path: Path) -> None:
    new = ASYNC_OLD.replace("application/json", "application/avro")
    findings = asyncapi_breaking_changes(
        _async(tmp_path / "o", {"a.yaml": ASYNC_OLD}),
        _async(tmp_path / "n", {"a.yaml": new}))
    assert [f for f in findings if f.id == "ASYNC016"]


# ---------------------------------------------------------------------------
# Unknown-first policy (§16.4): partial evidence never upgrades to BREAKING
# ---------------------------------------------------------------------------


def test_unknown_classification_carries_unknown_fact(tmp_path: Path) -> None:
    """Unresolvable structures classify UNKNOWN — the finding carries the
    recorded unknowns, never a bare BREAKING verdict."""
    old = NULLABLE_BASE.replace(
        "schema: {$ref: '#/components/schemas/Pet'}", "schema: {}")
    new = NULLABLE_BASE.replace(
        "schema: {$ref: '#/components/schemas/Pet'}",
        "schema: {type: object, properties: {x: {type: string}}}",
    )
    diff = diff_models(_oapi(tmp_path / "o", {"a.yaml": old}),
                       _oapi(tmp_path / "n", {"a.yaml": new}))
    unknowns = [c for c in diff.changes
                if c.classification is CompatibilityClass.UNKNOWN]
    assert unknowns
    finding = next(
        f for f in diff.findings
        if f.confidence is Confidence.UNKNOWN)
    assert finding.unknowns


def test_candidate_class_never_claims_breaking(tmp_path: Path) -> None:
    """Directive drift and union-add stay POTENTIALLY — distinction test."""
    from forge_doctor_api.checks.graphql import graphql_breaking_changes
    new = GQL_OLD.replace("type Pet { id: ID! }",
                          "type Pet @auth { id: ID! }")
    findings = graphql_breaking_changes(
        _gql(tmp_path / "o", GQL_OLD), _gql(tmp_path / "n", new))
    assert findings  # the directive change is detected
    assert all(f.severity.value != "critical" for f in findings)


# ---------------------------------------------------------------------------
# Client-impact breadth (§17): Feign, generated, gRPC stub, GraphQL doc
# ---------------------------------------------------------------------------

FEIGN = """package acme;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

@FeignClient(name = "orders")
@RequestMapping("/v1")
public interface OrdersClient {
    @GetMapping("/orders")
    List<Order> list();
    @PostMapping("/orders/{id}/pay")
    void pay(String id);
}
"""


def test_java_feign_extracted(tmp_path: Path) -> None:
    model = scan_clients(_write(tmp_path, {"svc/OrdersClient.java": FEIGN}),
                         ["svc/OrdersClient.java"])
    sites = {s.path: s for s in model.call_sites}
    assert "/v1/orders" in sites
    assert "/v1/orders/{id}/pay" in sites
    assert sites["/v1/orders"].library == "feign"
    assert sites["/v1/orders"].method == "GET"


def test_java_no_feign_no_sites(tmp_path: Path) -> None:
    """A plain Java class is not a client — no fabrication."""
    model = scan_clients(
        _write(tmp_path, {"svc/Util.java": "package a;\nclass Util {}"}),
        ["svc/Util.java"])
    assert model.call_sites == ()


GRPC_STUB = """import grpc
import orders_pb2_grpc

channel = grpc.insecure_channel("orders:443")
stub = orders_pb2_grpc.OrdersStub(channel)
resp = stub.GetOrder(request)
"""


def test_python_grpc_stub_extracted(tmp_path: Path) -> None:
    model = scan_clients(_write(tmp_path, {"svc/client.py": GRPC_STUB}),
                         ["svc/client.py"])
    (site,) = model.call_sites
    assert site.library == "grpc-stub"
    assert site.operation == "GetOrder"


GEN_API = """from openapi_client.api import pets_api
from openapi_client import api_client

client = api_client.ApiClient()
pets = pets_api.PetsApi(client)
pets.list_pets(limit=10)
"""


def test_python_generated_openapi_extracted(tmp_path: Path) -> None:
    model = scan_clients(_write(tmp_path, {"svc/gen.py": GEN_API}),
                         ["svc/gen.py"])
    (site,) = model.call_sites
    assert site.library == "openapi-generated"
    assert site.operation == "list_pets"


GQL_DOC = """query GetUser($id: ID!) {
  user(id: $id) { id name email }
}
mutation UpdateName($id: ID!, $name: String!) {
  updateUser(id: $id, name: $name) { name }
}
"""


def test_graphql_document_extracted(tmp_path: Path) -> None:
    model = scan_clients(
        _write(tmp_path, {"app/queries.graphql": GQL_DOC}),
        ["app/queries.graphql"])
    ops = {s.operation for s in model.call_sites}
    assert ops == {"GetUser", "UpdateName"}
    site = next(s for s in model.call_sites if s.operation == "GetUser")
    assert "email" in site.response_fields


GQL_TEMPLATE = """import { gql } from '@apollo/client';
const Q = gql`
  query GetPet { pet(id: "1") { name } }
`;
"""


def test_gql_template_extracted(tmp_path: Path) -> None:
    model = scan_clients(
        _write(tmp_path, {"app/q.ts": GQL_TEMPLATE}), ["app/q.ts"])
    (site,) = model.call_sites
    assert site.operation == "GetPet"
    assert site.language.value == "graphql"


def test_graphql_schema_file_not_a_client(tmp_path: Path) -> None:
    """An SDL `.graphql` contract file yields no client sites."""
    model = scan_clients(
        _write(tmp_path, {"api/schema.graphql": "type Query { x: Int }"}),
        ["api/schema.graphql"])
    assert model.call_sites == ()


# ---------------------------------------------------------------------------
# ServiceGraph adversarial identity (§14): exact match only, no fuzzy joins
# ---------------------------------------------------------------------------


def _entity(kind: str, ident: str, *, domain: str = "test") -> Entity:
    return Entity(
        id=entity_id(kind, domain, ident),
        kind=EntityKind.SERVICE if kind == "service" else EntityKind.ENDPOINT,
        name=ident,
    )


def _edge(a: Entity, b: Entity) -> Relationship:
    return Relationship(
        kind=RelationshipKind.DEPENDS_ON,
        source_id=a.id,
        target_id=b.id,
        confidence=Confidence.HIGH,
        evidence=(
            Evidence(kind=EvidenceKind.STATIC, source="t.yaml", summary="dep"),
        ),
    )


def test_same_route_string_in_two_services_stays_distinct() -> None:
    g = ServiceGraph()
    a = _entity("endpoint", "GET /health", domain="svc-a")
    b = _entity("endpoint", "GET /health", domain="svc-b")
    g.add_entity(a)
    g.add_entity(b)
    assert len(g) == 2
    assert g.get(a.id) is not g.get(b.id)


def test_same_service_name_in_two_repos_stays_distinct() -> None:
    g = ServiceGraph()
    a = _entity("service", "payments", domain="repo-a")
    b = _entity("service", "payments", domain="repo-b")
    g.add_entity(a)
    g.add_entity(b)
    assert a.id != b.id  # domain qualifier prevents fuzzy merge
    assert len(g) == 2


def test_conflicting_redefinition_rejected_not_merged() -> None:
    g = ServiceGraph()
    a = _entity("service", "svc")
    g.add_entity(a)
    with pytest.raises(GraphError):
        g.add_entity(Entity(
            id=a.id, kind=EntityKind.SERVICE, name="svc-renamed"))


def test_relationship_join_requires_exact_ids() -> None:
    g = ServiceGraph()
    a = _entity("service", "a")
    b = _entity("service", "b")
    g.add_entity(a)
    g.add_entity(b)
    g.add_relationship(_edge(a, b))
    # near-miss id (trailing space) must NOT join
    assert g.get(a.id + " ") is None
    # canonical but unregistered id: the graph refuses the edge
    ghost = _entity("service", "a2")
    near = Relationship(
        kind=RelationshipKind.DEPENDS_ON,
        source_id=ghost.id, target_id=b.id,
        confidence=Confidence.HIGH,
        evidence=(
            Evidence(kind=EvidenceKind.STATIC, source="t.yaml", summary="dep"),
        ))
    with pytest.raises(GraphError):
        g.add_relationship(near)
    # malformed id (trailing space): the model refuses before the graph
    from forge_doctor_api.core.models import ModelError
    with pytest.raises(ModelError):
        Relationship(
            kind=RelationshipKind.DEPENDS_ON,
            source_id=a.id + " ", target_id=b.id,
            confidence=Confidence.HIGH,
            evidence=(
                Evidence(kind=EvidenceKind.STATIC, source="t.yaml",
                         summary="dep"),
            ))


def test_deprecation_readiness_emitted_with_unknowns_when_signals_absent(
    tmp_path: Path,
) -> None:
    """§spec-087: DeprecationReadiness exists in fleet — emitted with
    unknowns when runtime/client signals are absent (never invented)."""
    from datetime import UTC, datetime

    from forge_doctor_api.fleet import build_fleet_report
    from forge_doctor_api.workspace import load_workspace

    base = _write(tmp_path / "ws", {
        "forge-doctor-api.workspace.yaml":
            "name: t\nmembers:\n"
            "  - {name: legacy, path: legacy, role: service}\n",
        "legacy/api.yaml": """openapi: "3.0.3"
info: {title: L, version: "1.0", deprecated: true,
       x-deprecation-date: "2026-06-01", x-sunset-date: "2027-01-01"}
paths:
  /old:
    get:
      operationId: old
      responses: {'200': {description: ok}}
""",
    })
    ctx = ProjectContext.from_root(
        base.root, clock=lambda: datetime(2026, 10, 3, tzinfo=UTC))
    ws = load_workspace(ctx)
    assert ws is not None
    rep = build_fleet_report(ctx, ws)
    dep = next((d for d in rep.deprecations if d.repo == "legacy"), None)
    assert dep is not None
    assert dep.observed_traffic is None  # no runtime evidence
    assert dep.unknowns                  # unknowns recorded, not guessed
