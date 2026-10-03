"""`OpenApiProjectModel` (§10.1).

Every element carries a `SourceLocation` (project-relative path, 1-based line
and column when known) and the JSON `pointer` of the element inside its
document. Raw OpenAPI fragments (schemas, parameter schemas, server
variables, extension values) are kept verbatim as JSON-compatible values;
`$ref`s inside them are never inlined — resolution results live in
`OpenApiProjectModel.references`, so recursive schemas stay finite.

Collections are sorted by (path, pointer), so the serialized model is
byte-identical for identical input. This module models; it emits no
findings (OAS checks consume it later).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from forge_doctor_api.core.models import Model, SourceLocation

OPENAPI_MODEL_SCHEMA_VERSION = "1.0"


class DocumentStatus(StrEnum):
    """Outcome of loading one file.

    - PARSED: OpenAPI root document with a supported version.
    - FRAGMENT: non-root file reached through a cross-file `$ref`.
    - NOT_OPENAPI: well-formed, but lacks the strong `openapi` marker (§101).
    - MALFORMED: not parseable as YAML/JSON.
    - INVALID_VERSION: has an `openapi` field that is not a `MAJOR.MINOR.PATCH` string.
    - UNSUPPORTED_VERSION: a version outside the bundled knowledge pack (e.g. 2.0, 4.0.0).
    - UNREADABLE: missing, outside the project root, or not UTF-8.
    """

    PARSED = "PARSED"
    FRAGMENT = "FRAGMENT"
    NOT_OPENAPI = "NOT_OPENAPI"
    MALFORMED = "MALFORMED"
    INVALID_VERSION = "INVALID_VERSION"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    UNREADABLE = "UNREADABLE"


class IssueCode(StrEnum):
    """Structured parse problems; inputs for later OAS checks, not findings."""

    MALFORMED = "MALFORMED"
    NOT_OPENAPI = "NOT_OPENAPI"
    INVALID_VERSION = "INVALID_VERSION"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    UNREADABLE = "UNREADABLE"
    DUPLICATE_KEY = "DUPLICATE_KEY"
    INVALID_REF = "INVALID_REF"
    MISSING_REF_TARGET = "MISSING_REF_TARGET"


class RefStatus(StrEnum):
    """Resolution outcome of one `$ref` (or `$dynamicRef`).

    - RESOLVED: target found (local, relative, or cross-file).
    - EXTERNAL: remote URL / URN / other scheme; recorded, never fetched (§10.2, §129).
    - OUTSIDE_ROOT: file target escapes the project root; never read.
    - MISSING: target file or JSON pointer does not exist.
    - INVALID: not a usable reference string.
    - DYNAMIC: `$dynamicRef` (JSON Schema 2020-12); resolved only at
      evaluation time, so the target is UNKNOWN statically.
    """

    RESOLVED = "RESOLVED"
    EXTERNAL = "EXTERNAL"
    OUTSIDE_ROOT = "OUTSIDE_ROOT"
    MISSING = "MISSING"
    INVALID = "INVALID"
    DYNAMIC = "DYNAMIC"


class OperationSource(StrEnum):
    PATH = "PATH"
    WEBHOOK = "WEBHOOK"
    CALLBACK = "CALLBACK"


class CycleKind(StrEnum):
    """- ALIAS: `$ref` chain that never reaches a concrete object (unresolvable).
    - RECURSIVE: a target that (transitively) contains a `$ref` back to itself,
      e.g. a tree schema; valid OpenAPI, but consumers must not inline it.
    """

    ALIAS = "ALIAS"
    RECURSIVE = "RECURSIVE"


@dataclass(frozen=True, kw_only=True)
class OpenApiIssue(Model):
    code: IssueCode
    message: str
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class OpenApiDocument(Model):
    location: SourceLocation
    format: str
    status: DocumentStatus
    openapi_version: str | None = None
    version_family: str | None = None
    title: str | None = None
    api_version: str | None = None
    json_schema_dialect: str | None = None
    self_uri: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiServer(Model):
    location: SourceLocation
    pointer: str
    url: str
    description: str | None = None
    variables: dict[str, Any] | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiPathItem(Model):
    location: SourceLocation
    pointer: str
    path: str
    ref: str | None = None
    summary: str | None = None
    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiOperation(Model):
    """`path` is the path template, webhook name, or callback expression (see `source`)."""

    location: SourceLocation
    pointer: str
    source: OperationSource
    method: str
    path: str
    identity: str
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None
    deprecated: bool = False
    tags: tuple[str, ...] = ()
    parameter_pointers: tuple[str, ...] = ()
    request_body_pointer: str | None = None
    response_pointers: tuple[str, ...] = ()
    callback_pointers: tuple[str, ...] = ()
    has_security: bool = False


@dataclass(frozen=True, kw_only=True)
class OpenApiParameter(Model):
    """A parameter definition. `name`/`location_in` are None when only a `$ref` is present."""

    location: SourceLocation
    pointer: str
    name: str | None = None
    location_in: str | None = None
    required: bool = False
    deprecated: bool = False
    ref: str | None = None
    schema: Any = None
    component_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiRequestBody(Model):
    location: SourceLocation
    pointer: str
    required: bool = False
    content_types: tuple[str, ...] = ()
    ref: str | None = None
    component_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiResponse(Model):
    """`status` is the status code / `default` (operations) or None (components)."""

    location: SourceLocation
    pointer: str
    status: str | None = None
    description: str | None = None
    content_types: tuple[str, ...] = ()
    ref: str | None = None
    component_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiSchema(Model):
    location: SourceLocation
    pointer: str
    name: str
    content: Any = None


@dataclass(frozen=True, kw_only=True)
class OpenApiCallback(Model):
    location: SourceLocation
    pointer: str
    name: str
    expressions: tuple[str, ...] = ()
    ref: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiWebhook(Model):
    location: SourceLocation
    pointer: str
    name: str
    methods: tuple[str, ...] = ()
    ref: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiSecurityScheme(Model):
    location: SourceLocation
    pointer: str
    name: str
    type: str | None = None
    scheme: str | None = None
    bearer_format: str | None = None
    location_in: str | None = None
    parameter_name: str | None = None
    open_id_connect_url: str | None = None
    flows: dict[str, Any] | None = None
    ref: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiSchemeUse(Model):
    """A security scheme name plus required scopes inside one requirement.

    Stored as a value rather than a mapping key so scheme names such as
    `apiKey` survive key-based secret redaction.
    """

    name: str
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class OpenApiSecurityRequirement(Model):
    """One alternative of a `security` list; empty `schemes` means anonymous access.

    `owner_pointer` is `""` for the document default or the operation pointer.
    """

    location: SourceLocation
    pointer: str
    owner_pointer: str
    schemes: tuple[OpenApiSchemeUse, ...] = ()


@dataclass(frozen=True, kw_only=True)
class OpenApiTag(Model):
    location: SourceLocation
    pointer: str
    name: str
    description: str | None = None
    parent: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiExternalDocs(Model):
    location: SourceLocation
    pointer: str
    url: str | None = None
    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpenApiExtension(Model):
    """A specification extension (`x-*`); `owner_pointer` is the object it extends."""

    location: SourceLocation
    pointer: str
    owner_pointer: str
    name: str
    value: Any = None


@dataclass(frozen=True, kw_only=True)
class OpenApiReference(Model):
    location: SourceLocation
    pointer: str
    ref: str
    status: RefStatus
    keyword: str = "$ref"
    target_path: str | None = None
    target_pointer: str | None = None


@dataclass(frozen=True, kw_only=True)
class UnresolvedExternalRef(Model):
    """A reference that was recorded but never fetched or read (§10.2, §129)."""

    location: SourceLocation
    pointer: str
    ref: str
    reason: RefStatus


@dataclass(frozen=True, kw_only=True)
class ReferenceCycle(Model):
    """A strongly connected set of `$ref` targets (`path#pointer`), sorted.

    `location` is the first (sorted) `$ref` site that closes the cycle.
    """

    kind: CycleKind
    members: tuple[str, ...]
    location: SourceLocation
    pointer: str


@dataclass(frozen=True, kw_only=True)
class OpenApiProjectModel(Model):
    schema_version: str
    documents: tuple[OpenApiDocument, ...] = ()
    servers: tuple[OpenApiServer, ...] = ()
    paths: tuple[OpenApiPathItem, ...] = ()
    operations: tuple[OpenApiOperation, ...] = ()
    parameters: tuple[OpenApiParameter, ...] = ()
    request_bodies: tuple[OpenApiRequestBody, ...] = ()
    responses: tuple[OpenApiResponse, ...] = ()
    schemas: tuple[OpenApiSchema, ...] = ()
    callbacks: tuple[OpenApiCallback, ...] = ()
    webhooks: tuple[OpenApiWebhook, ...] = ()
    security_schemes: tuple[OpenApiSecurityScheme, ...] = ()
    security_requirements: tuple[OpenApiSecurityRequirement, ...] = ()
    tags: tuple[OpenApiTag, ...] = ()
    external_docs: tuple[OpenApiExternalDocs, ...] = ()
    extensions: tuple[OpenApiExtension, ...] = ()
    references: tuple[OpenApiReference, ...] = ()
    unresolved_external_refs: tuple[UnresolvedExternalRef, ...] = ()
    cycles: tuple[ReferenceCycle, ...] = ()
    issues: tuple[OpenApiIssue, ...] = ()
