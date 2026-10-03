"""GraphQL semantic model (§22, §24, §184).

One `GraphQLProjectModel` aggregates SDL schemas and introspection-JSON
exports. `graphql-core` is an optional extra; when absent, documents are
still detected by their strong markers but fields stay unparsed and the
model records a structured issue instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Model,
    SourceLocation,
    UnknownFact,
)

GRAPHQL_MODEL_SCHEMA_VERSION = "graphql-model/1"


class GraphQLDocumentStatus(StrEnum):
    PARSED = "PARSED"
    MALFORMED = "MALFORMED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_GRAPHQL = "NOT_GRAPHQL"
    PARSER_UNAVAILABLE = "PARSER_UNAVAILABLE"


class GraphQLIssueCode(StrEnum):
    NOT_GRAPHQL = "NOT_GRAPHQL"
    MALFORMED = "MALFORMED"
    PARSER_UNAVAILABLE = "PARSER_UNAVAILABLE"


class GraphQLTypeKind(StrEnum):
    OBJECT = "object"
    INTERFACE = "interface"
    UNION = "union"
    ENUM = "enum"
    SCALAR = "scalar"
    INPUT_OBJECT = "input_object"


class GraphQLOperationKind(StrEnum):
    QUERY = "query"
    MUTATION = "mutation"
    SUBSCRIPTION = "subscription"


@dataclass(frozen=True, kw_only=True)
class GraphQLIssue(Model):
    code: GraphQLIssueCode
    message: str
    location: SourceLocation | None = None


@dataclass(frozen=True, kw_only=True)
class GraphQLTypeRef(Model):
    """A flattened type reference: base name + list/nullable wrappers."""

    name: str
    nullable: bool = True
    is_list: bool = False
    item_nullable: bool = True


@dataclass(frozen=True, kw_only=True)
class GraphQLArgument(Model):
    name: str
    type: GraphQLTypeRef
    required: bool
    has_default: bool
    deprecated: bool = False
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GraphQLField(Model):
    name: str
    type: GraphQLTypeRef
    arguments: tuple[GraphQLArgument, ...] = ()
    directives: tuple[str, ...] = ()
    deprecated: bool = False
    deprecation_reason: str | None = None
    required: bool = False  # input-object fields only
    has_default: bool = False  # input-object fields only
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GraphQLType(Model):
    name: str
    kind: GraphQLTypeKind
    fields: tuple[GraphQLField, ...] = ()
    enum_values: tuple[str, ...] = ()
    deprecated_enum_values: tuple[str, ...] = ()
    union_members: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    directives: tuple[str, ...] = ()
    operation_root: GraphQLOperationKind | None = None
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GraphQLResolver(Model):
    """A resolvable field: root operation fields and fields with args."""

    type_name: str
    field_name: str
    auth_evidence: tuple[str, ...] = ()
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GraphQLQueryShape(Model):
    """§24 transparent complexity metrics - additive formula, no magic score.

    estimated_complexity = field_count + list_expansions * depth
    """

    depth: int
    field_count: int
    list_expansions: int
    resolver_count: int
    estimated_complexity: int


@dataclass(frozen=True, kw_only=True)
class GraphQLClientQuery(Model):
    """A client query string found in source (§184)."""

    operation: str | None
    operation_kind: GraphQLOperationKind
    shape: GraphQLQueryShape
    fields_touched: tuple[str, ...] = ()  # "Type.field" pairs, schema-resolved
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class IntrospectionEvidence(Model):
    """Config evidence about introspection exposure (never assumed)."""

    enabled: bool
    location: SourceLocation
    detail: str


@dataclass(frozen=True, kw_only=True)
class GraphQLDocument(Model):
    path: str
    status: GraphQLDocumentStatus
    source: str  # "sdl" | "introspection"
    location: SourceLocation | None = None


@dataclass(frozen=True, kw_only=True)
class GraphQLProjectModel(Model):
    schema_version: str = GRAPHQL_MODEL_SCHEMA_VERSION
    documents: tuple[GraphQLDocument, ...] = ()
    types: tuple[GraphQLType, ...] = ()
    resolvers: tuple[GraphQLResolver, ...] = ()
    client_queries: tuple[GraphQLClientQuery, ...] = ()
    directives: tuple[str, ...] = ()
    introspection: tuple[IntrospectionEvidence, ...] = ()
    issues: tuple[GraphQLIssue, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    def type_named(self, name: str) -> GraphQLType | None:
        for t in self.types:
            if t.name == name:
                return t
        return None

    def operation_fields(self, kind: GraphQLOperationKind) -> tuple[GraphQLField, ...]:
        for t in self.types:
            if t.operation_root is kind:
                return t.fields
        return ()
