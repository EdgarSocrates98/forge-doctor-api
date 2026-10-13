"""GraphQL semantic model (§22, §24, §184)."""

from forge_doctor_api.analyzers.graphql.client import extract_client_queries
from forge_doctor_api.analyzers.graphql.compat import diff_graphql_schemas
from forge_doctor_api.analyzers.graphql.graph import graphql_graph
from forge_doctor_api.analyzers.graphql.model import (
    GRAPHQL_MODEL_SCHEMA_VERSION,
    GraphQLArgument,
    GraphQLClientQuery,
    GraphQLDocument,
    GraphQLDocumentStatus,
    GraphQLField,
    GraphQLIssue,
    GraphQLIssueCode,
    GraphQLOperationKind,
    GraphQLProjectModel,
    GraphQLQueryShape,
    GraphQLResolver,
    GraphQLType,
    GraphQLTypeKind,
    GraphQLTypeRef,
    IntrospectionEvidence,
)
from forge_doctor_api.analyzers.graphql.parser import load_graphql_project
from forge_doctor_api.analyzers.graphql.shape import query_shape

__all__ = [
    "GRAPHQL_MODEL_SCHEMA_VERSION",
    "GraphQLArgument",
    "GraphQLClientQuery",
    "GraphQLDocument",
    "GraphQLDocumentStatus",
    "GraphQLField",
    "GraphQLIssue",
    "GraphQLIssueCode",
    "GraphQLOperationKind",
    "GraphQLProjectModel",
    "GraphQLQueryShape",
    "GraphQLResolver",
    "GraphQLType",
    "GraphQLTypeKind",
    "GraphQLTypeRef",
    "IntrospectionEvidence",
    "diff_graphql_schemas",
    "extract_client_queries",
    "graphql_graph",
    "load_graphql_project",
    "query_shape",
]
