"""GraphQL model + GQL### check tests (spec 012, §22-24, §184)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_doctor_api.analyzers.graphql import (
    GraphQLDocumentStatus,
    GraphQLTypeKind,
    extract_client_queries,
    graphql_graph,
    load_graphql_project,
)
from forge_doctor_api.checks.graphql import (
    graphql_breaking_changes,
    run_graphql_checks,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Confidence

SDL = """directive @auth(requires: String) on FIELD_DEFINITION | OBJECT

type Query {
  user(id: ID!): User @auth(requires: "user:read")
  users: [User!]!
}
type User {
  id: ID!
  name: String
  friends: [User!]
  old: String @deprecated(reason: "use name")
}
enum Role { ADMIN USER }
"""


def _model(root: Path, files: dict[str, str], with_queries: bool = True):
    pytest.importorskip("graphql")
    for name, text in files.items():
        t = root / name
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
    ctx = ProjectContext.from_root(root)
    model = load_graphql_project(ctx, list(files))
    if with_queries:
        qs, unknowns = extract_client_queries(ctx, list(files), model)
        model = load_graphql_project(ctx, list(files), client_queries=qs)
        assert isinstance(unknowns, tuple)
    return model


def _ids(findings) -> list[str]:
    return [f.id for f in findings]


# -- parsing + detection -----------------------------------------------------------


def test_sdl_parses(tmp_path: Path) -> None:
    model = _model(tmp_path, {"s.graphql": SDL})
    assert model.documents[0].status is GraphQLDocumentStatus.PARSED
    kinds = {t.name: t.kind for t in model.types}
    assert kinds["User"] is GraphQLTypeKind.OBJECT
    assert kinds["Role"] is GraphQLTypeKind.ENUM
    query = model.type_named("Query")
    assert query is not None and query.operation_root is not None
    user_field = next(f for f in query.fields if f.name == "user")
    assert user_field.arguments[0].required


def test_introspection_json_parses(tmp_path: Path) -> None:
    intro = {
        "__schema": {
            "queryType": {"name": "Query"},
            "mutationType": None,
            "subscriptionType": None,
            "types": [
                {
                    "kind": "OBJECT",
                    "name": "Query",
                    "fields": [
                        {
                            "name": "ping",
                            "args": [],
                            "type": {
                                "kind": "SCALAR",
                                "name": "String",
                                "ofType": None,
                            },
                            "isDeprecated": False,
                            "deprecationReason": None,
                        }
                    ],
                    "interfaces": [],
                    "enumValues": None,
                    "possibleTypes": None,
                    "inputFields": None,
                },
                {
                    "kind": "SCALAR",
                    "name": "String",
                    "fields": None,
                    "interfaces": None,
                    "enumValues": None,
                    "possibleTypes": None,
                    "inputFields": None,
                },
            ],
            "directives": [],
        }
    }
    import json

    model = _model(tmp_path, {"export.json": json.dumps(intro)})
    assert model.documents[0].status is GraphQLDocumentStatus.PARSED
    assert model.documents[0].source == "introspection"
    assert model.type_named("Query") is not None


def test_graphql_looking_json_not_detected(tmp_path: Path) -> None:
    """A request payload `{query: ...}` is NOT a schema (§100 adversarial)."""
    payload = '{"query": "{ user { id } }", "variables": {}}'
    model = _model(tmp_path, {"req.json": payload})
    assert model.documents == ()
    assert model.types == ()


def test_malformed_sdl_is_issue(tmp_path: Path) -> None:
    model = _model(tmp_path, {"bad.graphql": "type Query {{{"})
    assert model.documents[0].status is GraphQLDocumentStatus.MALFORMED
    assert any(i.code.value == "MALFORMED" for i in model.issues)


def test_parser_unavailable_degrades_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without graphql-core, detected files degrade to UNKNOWN state (§3)."""
    import forge_doctor_api.analyzers.graphql.parser as parser_mod

    monkeypatch.setattr(parser_mod, "_graphql", lambda: None)
    (tmp_path / "s.graphql").write_text(SDL)
    ctx = ProjectContext.from_root(tmp_path)
    model = load_graphql_project(ctx, ["s.graphql"])
    assert model.documents[0].status is GraphQLDocumentStatus.PARSER_UNAVAILABLE
    assert any(i.code.value == "PARSER_UNAVAILABLE" for i in model.issues)
    assert model.types == ()


def test_comment_only_file_not_detected(tmp_path: Path) -> None:
    proto_like = "# graphql-like comment\n# type Query { x: Int }\n"
    model = _model(tmp_path, {"notes.md": proto_like})
    assert model.documents == ()


def test_custom_root_name(tmp_path: Path) -> None:
    sdl = "schema { query: Root }\ntype Root { ping: String }\n"
    model = _model(tmp_path, {"s.graphql": sdl})
    root = model.type_named("Root")
    assert root is not None and root.operation_root is not None
    assert model.operation_fields(root.operation_root)


# -- graph ---------------------------------------------------------------------------


def test_graph_entities_and_edges(tmp_path: Path) -> None:
    model = _model(tmp_path, {"s.graphql": SDL})
    g = graphql_graph(model)
    kinds = {e.kind for e in g.entities()}
    assert {"graphql_type", "graphql_resolver"} <= kinds
    rels = {r.kind for r in g.relationships()}
    assert "EXPOSES" in rels


# -- query shape + client extraction ----------------------------------------------------


def test_query_shape_transparent(tmp_path: Path) -> None:
    client = 'const q = gql`query Get { user(id: "1") { friends { name } } }`;'
    model = _model(tmp_path, {"s.graphql": SDL, "c.ts": client})
    assert len(model.client_queries) == 1
    q = model.client_queries[0]
    assert q.shape.depth == 3
    assert q.shape.field_count == 3
    # estimated_complexity = field_count + list_expansions * depth (documented)
    assert q.shape.estimated_complexity == (
        q.shape.field_count + q.shape.list_expansions * q.shape.depth
    )
    assert "User.friends" in q.fields_touched


def test_dynamic_query_becomes_unknown(tmp_path: Path) -> None:
    client = "const q = gql`query { user(id: ${uid}) { id } }`;"
    ctx_files = {"s.graphql": SDL, "c.ts": client}
    for name, text in ctx_files.items():
        (tmp_path / name).write_text(text)
    ctx = ProjectContext.from_root(tmp_path)
    model = load_graphql_project(ctx, list(ctx_files))
    _, unknowns = extract_client_queries(ctx, list(ctx_files), model)
    assert unknowns


# -- single-schema checks --------------------------------------------------------------


def test_gql001_deprecated_field_with_client(tmp_path: Path) -> None:
    client = 'const q = gql`query { user(id: "1") { old } }`;'
    model = _model(tmp_path, {"s.graphql": SDL, "c.ts": client})
    assert "GQL001" in _ids(run_graphql_checks(model))


def test_gql001_quiet_without_client(tmp_path: Path) -> None:
    model = _model(tmp_path, {"s.graphql": SDL})
    assert "GQL001" not in _ids(run_graphql_checks(model))


def test_gql006_resolver_without_auth(tmp_path: Path) -> None:
    sdl = "type Query { user(id: ID!): User }\ntype User { id: ID! }\n"
    model = _model(tmp_path, {"s.graphql": sdl})
    findings = run_graphql_checks(model)
    assert "GQL006" in _ids(findings)
    f = next(f for f in findings if f.id == "GQL006")
    assert f.confidence is Confidence.LOW and f.unknowns


def test_gql006_clean_with_auth_directive(tmp_path: Path) -> None:
    sdl = (
        "directive @auth on FIELD_DEFINITION\n"
        "type Query { user(id: ID!): User @auth }\n"
        "type User { id: ID! }\n"
    )
    model = _model(tmp_path, {"s.graphql": sdl})
    assert "GQL006" not in _ids(run_graphql_checks(model))


def test_gql007_unbounded_list(tmp_path: Path) -> None:
    model = _model(tmp_path, {"s.graphql": SDL})
    assert "GQL007" in _ids(run_graphql_checks(model))


def test_gql007_clean_with_pagination(tmp_path: Path) -> None:
    sdl = "type Query { users(first: Int, after: String): [User!]! }\ntype User { id: ID! }\n"
    model = _model(tmp_path, {"s.graphql": sdl})
    assert "GQL007" not in _ids(run_graphql_checks(model))


def test_gql008_recursive_types(tmp_path: Path) -> None:
    model = _model(tmp_path, {"s.graphql": SDL})
    findings = run_graphql_checks(model)
    assert "GQL008" in _ids(findings)


def test_gql009_n1_candidate(tmp_path: Path) -> None:
    model = _model(tmp_path, {"s.graphql": SDL})
    f = next(f for f in run_graphql_checks(model) if f.id == "GQL009")
    assert f.confidence is Confidence.LOW and f.unknowns


def test_gql010_introspection_evidence(tmp_path: Path) -> None:
    files = {"s.graphql": SDL, "server.yaml": "graphql:\n  introspection: true\n"}
    model = _model(tmp_path, files)
    findings = run_graphql_checks(model)
    assert "GQL010" in _ids(findings)
    f = next(f for f in findings if f.id == "GQL010")
    assert "enabled" in f.description


def test_gql010_no_evidence_candidate(tmp_path: Path) -> None:
    model = _model(tmp_path, {"s.graphql": SDL})
    f = next(f for f in run_graphql_checks(model) if f.id == "GQL010")
    assert "undetermined" in f.description and f.unknowns


# -- schema diff (GQL002-005 via unified compat classes) --------------------------------

OLD = """type Query { user(id: ID!): User }
type User { id: ID! name: String email: String }
enum Role { ADMIN USER }
"""


def test_gql002_field_removed(tmp_path: Path) -> None:
    new = OLD.replace(" email: String", "")
    old = _model(tmp_path / "o", {"s.graphql": OLD})
    new_m = _model(tmp_path / "n", {"s.graphql": new})
    assert "GQL002" in _ids(graphql_breaking_changes(old, new_m))


def test_gql003_required_argument_added(tmp_path: Path) -> None:
    new = OLD.replace("user(id: ID!)", "user(id: ID!, region: String!)")
    old = _model(tmp_path / "o", {"s.graphql": OLD})
    new_m = _model(tmp_path / "n", {"s.graphql": new})
    assert "GQL003" in _ids(graphql_breaking_changes(old, new_m))


def test_gql004_nullable_to_nonnull_output(tmp_path: Path) -> None:
    new = OLD.replace("name: String", "name: String!")
    old = _model(tmp_path / "o", {"s.graphql": OLD})
    new_m = _model(tmp_path / "n", {"s.graphql": new})
    f = next(
        f for f in graphql_breaking_changes(old, new_m) if f.id == "GQL004"
    )
    assert "response" in f.description or "RESPONSE" in f.description


def test_gql004_nullable_to_nonnull_input(tmp_path: Path) -> None:
    old_sdl = """type Query { search(q: String): [String!]! }
input Filter { term: String }
type Mutation { run(f: Filter): String }
"""
    new_sdl = old_sdl.replace("term: String", "term: String!")
    old = _model(tmp_path / "o", {"s.graphql": old_sdl})
    new_m = _model(tmp_path / "n", {"s.graphql": new_sdl})
    findings = [f for f in graphql_breaking_changes(old, new_m) if f.id == "GQL004"]
    assert findings and all("request" in f.description.lower() or "input" in f.description
                            for f in findings)


def test_gql005_enum_value_removed(tmp_path: Path) -> None:
    new = OLD.replace("ADMIN USER", "ADMIN")
    old = _model(tmp_path / "o", {"s.graphql": OLD})
    new_m = _model(tmp_path / "n", {"s.graphql": new})
    assert "GQL005" in _ids(graphql_breaking_changes(old, new_m))


def test_no_diff_no_findings(tmp_path: Path) -> None:
    old = _model(tmp_path / "o", {"s.graphql": OLD})
    new_m = _model(tmp_path / "n", {"s.graphql": OLD})
    assert graphql_breaking_changes(old, new_m) == ()


# -- determinism -----------------------------------------------------------------------


def test_determinism(tmp_path: Path) -> None:
    files = {"a.graphql": SDL, "b.graphql": OLD}
    one = _model(tmp_path / "x", files)
    two = _model(tmp_path / "y", files)
    assert one.to_dict() == two.to_dict()
    a, b = run_graphql_checks(one), run_graphql_checks(two)
    assert [f.to_dict() for f in a] == [f.to_dict() for f in b]
