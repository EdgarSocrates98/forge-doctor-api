"""GraphQL SDL + introspection export parsing (§22, §100, §101).

Detection requires a strong marker: a ``.graphql``/``.gql`` extension, or a
JSON document with a top-level ``__schema`` (or ``data.__schema``) object.
GraphQL-looking JSON payloads (``{query: ...}``) and proto-like comments do
not attribute. ``graphql-core`` is an optional extra - imported lazily; when
absent, detected documents become ``PARSER_UNAVAILABLE`` and the model
records a structured issue rather than guessing (§3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from forge_doctor_api.analyzers.graphql.model import (
    GraphQLArgument,
    GraphQLClientQuery,
    GraphQLDocument,
    GraphQLDocumentStatus,
    GraphQLField,
    GraphQLIssue,
    GraphQLIssueCode,
    GraphQLOperationKind,
    GraphQLProjectModel,
    GraphQLResolver,
    GraphQLType,
    GraphQLTypeKind,
    GraphQLTypeRef,
    IntrospectionEvidence,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation

if TYPE_CHECKING:
    from graphql import GraphQLSchema

_SDL_SUFFIXES = {".graphql", ".gql"}
_AUTH_DIRECTIVE = re.compile(r"auth|scope|permission|role|policy|requires|can\b", re.I)
_INTROSPECTION_KEY = re.compile(
    r"^\s*[\"']?introspection[\"']?\s*[:=]\s*[\"']?(true|false|enabled|disabled)",
    re.IGNORECASE | re.MULTILINE,
)
_CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".env"}


def _graphql() -> Any | None:
    try:
        import graphql

        return graphql
    except ImportError:
        return None


def _loc(path: str, node: Any) -> SourceLocation:
    loc = getattr(node, "loc", None)
    token = getattr(loc, "start_token", None)
    return SourceLocation(
        path=path,
        line=getattr(token, "line", None),
        column=getattr(token, "column", None),
    )


def _type_ref(t: Any) -> GraphQLTypeRef:
    """Flatten a wrapped GraphQL type into name + list/nullability."""
    gql = _graphql()
    assert gql is not None  # callers gate on parser availability
    nullable = True
    is_list = False
    item_nullable = True
    node = t
    if gql.is_non_null_type(node):
        nullable = False
        node = node.of_type
    if gql.is_list_type(node):
        is_list = True
        inner = node.of_type
        if gql.is_non_null_type(inner):
            item_nullable = False
            inner = inner.of_type
        node = inner
    return GraphQLTypeRef(
        name=gql.get_named_type(node).name,
        nullable=nullable,
        is_list=is_list,
        item_nullable=item_nullable,
    )


def _directives(ast_node: Any) -> tuple[str, ...]:
    node = getattr(ast_node, "directives", None) or ()
    return tuple(sorted({d.name.value for d in node}))


def _field(path: str, name: str, f: Any) -> GraphQLField:
    gql = _graphql()
    assert gql is not None
    args = tuple(
        GraphQLArgument(
            name=aname,
            type=_type_ref(arg.type),
            required=(
                not _type_ref(arg.type).nullable
                and arg.default_value is gql.Undefined
            ),
            has_default=arg.default_value is not gql.Undefined,
            deprecated=arg.deprecation_reason is not None,
            location=_loc(path, getattr(arg, "ast_node", None)),
        )
        for aname, arg in sorted(f.args.items())
    )
    return GraphQLField(
        name=name,
        type=_type_ref(f.type),
        arguments=args,
        directives=_directives(getattr(f, "ast_node", None)),
        deprecated=f.deprecation_reason is not None,
        deprecation_reason=f.deprecation_reason,
        location=_loc(path, getattr(f, "ast_node", None)),
    )


def _input_field(path: str, name: str, f: Any) -> GraphQLField:
    gql = _graphql()
    assert gql is not None
    ref = _type_ref(f.type)
    return GraphQLField(
        name=name,
        type=ref,
        required=not ref.nullable and f.default_value is gql.Undefined,
        has_default=f.default_value is not gql.Undefined,
        deprecated=f.deprecation_reason is not None,
        deprecation_reason=f.deprecation_reason,
        location=_loc(path, getattr(f, "ast_node", None)),
    )


def _root_kind(schema: GraphQLSchema, type_name: str) -> GraphQLOperationKind | None:
    for root, kind in (
        (schema.query_type, GraphQLOperationKind.QUERY),
        (schema.mutation_type, GraphQLOperationKind.MUTATION),
        (schema.subscription_type, GraphQLOperationKind.SUBSCRIPTION),
    ):
        if root is not None and root.name == type_name:
            return kind
    return None


def _extract_schema(schema: GraphQLSchema, path: str) -> list[GraphQLType]:
    gql = _graphql()
    assert gql is not None
    out: list[GraphQLType] = []
    for name in sorted(schema.type_map):
        if name.startswith("__"):
            continue
        t: Any = schema.type_map[name]
        loc = _loc(path, getattr(t, "ast_node", None))
        directives = _directives(getattr(t, "ast_node", None))
        if gql.is_interface_type(t):
            out.append(
                GraphQLType(
                    name=name,
                    kind=GraphQLTypeKind.INTERFACE,
                    fields=tuple(
                        GraphQLField(
                            name=fname,
                            type=_type_ref(f.type),
                            deprecated=f.deprecation_reason is not None,
                            deprecation_reason=f.deprecation_reason,
                            location=_loc(path, getattr(f, "ast_node", None)),
                        )
                        for fname, f in sorted(t.fields.items())
                    ),
                    directives=directives,
                    location=loc,
                )
            )
        elif gql.is_object_type(t):
            out.append(
                GraphQLType(
                    name=name,
                    kind=GraphQLTypeKind.OBJECT,
                    operation_root=_root_kind(schema, name),
                    fields=tuple(
                        _field(path, fname, f)
                        for fname, f in sorted(t.fields.items())
                    ),
                    interfaces=tuple(sorted(i.name for i in t.interfaces)),
                    directives=directives,
                    location=loc,
                )
            )
        elif gql.is_union_type(t):
            out.append(
                GraphQLType(
                    name=name,
                    kind=GraphQLTypeKind.UNION,
                    union_members=tuple(sorted(m.name for m in t.types)),
                    directives=directives,
                    location=loc,
                )
            )
        elif gql.is_enum_type(t):
            out.append(
                GraphQLType(
                    name=name,
                    kind=GraphQLTypeKind.ENUM,
                    enum_values=tuple(sorted(t.values)),
                    deprecated_enum_values=tuple(
                        sorted(
                            v for v, ev in t.values.items() if ev.deprecation_reason
                        )
                    ),
                    directives=directives,
                    location=loc,
                )
            )
        elif gql.is_input_object_type(t):
            out.append(
                GraphQLType(
                    name=name,
                    kind=GraphQLTypeKind.INPUT_OBJECT,
                    fields=tuple(
                        _input_field(path, fname, f)
                        for fname, f in sorted(t.fields.items())
                    ),
                    directives=directives,
                    location=loc,
                )
            )
        elif gql.is_scalar_type(t):
            out.append(
                GraphQLType(
                    name=name,
                    kind=GraphQLTypeKind.SCALAR,
                    directives=directives,
                    location=loc,
                )
            )
    return out


def _resolvers(types: list[GraphQLType]) -> list[GraphQLResolver]:
    """Resolvers = root operation fields + any field taking arguments."""
    out: list[GraphQLResolver] = []
    for t in types:
        if t.kind is not GraphQLTypeKind.OBJECT:
            continue
        is_root = t.operation_root is not None
        for f in t.fields:
            if not is_root and not f.arguments:
                continue
            evidence = sorted(
                {
                    d
                    for d in (*f.directives, *t.directives)
                    if _AUTH_DIRECTIVE.search(d)
                }
            )
            out.append(
                GraphQLResolver(
                    type_name=t.name,
                    field_name=f.name,
                    auth_evidence=tuple(evidence),
                    location=f.location,
                )
            )
    return out


def _introspection_policy(
    context: ProjectContext, files: list[str]
) -> list[IntrospectionEvidence]:
    out: list[IntrospectionEvidence] = []
    for path in sorted(files):
        if Path(path).suffix.lower() not in _CONFIG_SUFFIXES:
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        for match in _INTROSPECTION_KEY.finditer(text):
            raw = match.group(1).lower()
            out.append(
                IntrospectionEvidence(
                    enabled=raw in {"true", "enabled"},
                    location=SourceLocation(
                        path=path, line=text[: match.start()].count("\n") + 1
                    ),
                    detail=match.group(0).strip(),
                )
            )
    return out


def load_graphql_project(
    context: ProjectContext,
    files: list[str],
    *,
    client_queries: tuple[GraphQLClientQuery, ...] = (),
) -> GraphQLProjectModel:
    gql = _graphql()
    documents: list[GraphQLDocument] = []
    issues: list[GraphQLIssue] = []
    types: list[GraphQLType] = []

    for path in sorted(files):
        suffix = Path(path).suffix.lower()
        if suffix in _SDL_SUFFIXES:
            try:
                text = context.read_text(path)
            except (OSError, UnicodeDecodeError):
                continue
            if gql is None:
                documents.append(
                    GraphQLDocument(
                        path=path,
                        status=GraphQLDocumentStatus.PARSER_UNAVAILABLE,
                        source="sdl",
                    )
                )
                issues.append(
                    GraphQLIssue(
                        code=GraphQLIssueCode.PARSER_UNAVAILABLE,
                        message="graphql-core is not installed; install the "
                        "'graphql' extra to parse SDL",
                        location=SourceLocation(path=path),
                    )
                )
                continue
            try:
                schema = gql.build_schema(text)
            except Exception as exc:  # untrusted input: GraphQLError family
                documents.append(
                    GraphQLDocument(
                        path=path, status=GraphQLDocumentStatus.MALFORMED, source="sdl"
                    )
                )
                issues.append(
                    GraphQLIssue(
                        code=GraphQLIssueCode.MALFORMED,
                        message=f"SDL parse failed: {exc}",
                        location=SourceLocation(path=path),
                    )
                )
                continue
            documents.append(
                GraphQLDocument(
                    path=path, status=GraphQLDocumentStatus.PARSED, source="sdl"
                )
            )
            types.extend(_extract_schema(schema, path))
        elif suffix == ".json":
            try:
                data = json.loads(context.read_text(path))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            schema_doc: Any = data.get("__schema")
            if schema_doc is None:
                inner = data.get("data")
                schema_doc = inner.get("__schema") if isinstance(inner, dict) else None
            if not isinstance(schema_doc, dict):
                continue  # no strong marker - GraphQL-looking JSON is ignored (§100)
            if gql is None:
                documents.append(
                    GraphQLDocument(
                        path=path,
                        status=GraphQLDocumentStatus.PARSER_UNAVAILABLE,
                        source="introspection",
                    )
                )
                continue
            holder = data if "__schema" in data else data.get("data", {})
            try:
                schema = gql.build_client_schema(holder)
            except Exception as exc:
                documents.append(
                    GraphQLDocument(
                        path=path,
                        status=GraphQLDocumentStatus.MALFORMED,
                        source="introspection",
                    )
                )
                issues.append(
                    GraphQLIssue(
                        code=GraphQLIssueCode.MALFORMED,
                        message=f"introspection build failed: {exc}",
                        location=SourceLocation(path=path),
                    )
                )
                continue
            documents.append(
                GraphQLDocument(
                    path=path,
                    status=GraphQLDocumentStatus.PARSED,
                    source="introspection",
                )
            )
            types.extend(_extract_schema(schema, path))

    types.sort(key=lambda t: (t.name, t.location.path))
    resolvers = _resolvers(types)
    directives = tuple(
        sorted(
            {d for t in types for f in t.fields for d in f.directives}
            | {d for t in types for d in t.directives}
        )
    )
    return GraphQLProjectModel(
        documents=tuple(documents),
        types=tuple(types),
        resolvers=tuple(resolvers),
        client_queries=client_queries,
        directives=directives,
        introspection=tuple(_introspection_policy(context, files)),
        issues=tuple(issues),
    )
