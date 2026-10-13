"""AsyncAPI semantic model (§20)."""

from forge_doctor_api.analyzers.asyncapi.compat import diff_asyncapi_models
from forge_doctor_api.analyzers.asyncapi.graph import async_graph
from forge_doctor_api.analyzers.asyncapi.model import (
    ASYNCAPI_MODEL_SCHEMA_VERSION,
    AsyncAction,
    AsyncApiChannel,
    AsyncApiDocument,
    AsyncApiIssue,
    AsyncApiMessage,
    AsyncApiOperation,
    AsyncApiProjectModel,
    AsyncApiSchema,
    AsyncApiSecurityRequirement,
    AsyncApiServer,
    AsyncDocumentStatus,
    AsyncIssueCode,
)
from forge_doctor_api.analyzers.asyncapi.parser import load_asyncapi_project

__all__ = [
    "ASYNCAPI_MODEL_SCHEMA_VERSION",
    "AsyncAction",
    "AsyncApiChannel",
    "AsyncApiDocument",
    "AsyncApiIssue",
    "AsyncApiMessage",
    "AsyncApiOperation",
    "AsyncApiProjectModel",
    "AsyncApiSchema",
    "AsyncApiSecurityRequirement",
    "AsyncApiServer",
    "AsyncDocumentStatus",
    "AsyncIssueCode",
    "async_graph",
    "diff_asyncapi_models",
    "load_asyncapi_project",
]
