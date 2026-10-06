"""`AsyncApiModel` (§20.1, spec 011).

2.x `publish`/`subscribe` channel verbs and 3.x `send`/`receive` operations
normalize into `AsyncAction.SEND`/`RECEIVE`: SEND = the application produces
onto the channel, RECEIVE = it consumes from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Model,
    SourceLocation,
)

ASYNCAPI_MODEL_SCHEMA_VERSION = "0.1"


class AsyncDocumentStatus(StrEnum):
    PARSED = "PARSED"
    NOT_ASYNCAPI = "NOT_ASYNCAPI"
    MALFORMED = "MALFORMED"
    INVALID_VERSION = "INVALID_VERSION"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    UNREADABLE = "UNREADABLE"


class AsyncIssueCode(StrEnum):
    MALFORMED = "MALFORMED"
    NOT_ASYNCAPI = "NOT_ASYNCAPI"
    INVALID_VERSION = "INVALID_VERSION"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    UNREADABLE = "UNREADABLE"
    INVALID_REF = "INVALID_REF"
    MISSING_REF_TARGET = "MISSING_REF_TARGET"


class AsyncAction(StrEnum):
    """Normalized 2.x/3.x direction: SEND produces, RECEIVE consumes."""

    SEND = "send"
    RECEIVE = "receive"


@dataclass(frozen=True, kw_only=True)
class AsyncApiIssue(Model):
    code: AsyncIssueCode
    message: str
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class AsyncApiDocument(Model):
    location: SourceLocation
    status: AsyncDocumentStatus
    asyncapi_version: str | None = None
    version_family: str | None = None
    title: str | None = None
    api_version: str | None = None


@dataclass(frozen=True, kw_only=True)
class AsyncApiChannel(Model):
    """A channel (2.x channel key or 3.x `address`)."""

    location: SourceLocation
    pointer: str
    name: str
    address: str | None = None
    parameters: tuple[str, ...] = ()
    message_pointers: tuple[str, ...] = ()
    bindings: tuple[str, ...] = ()
    markers: tuple[str, ...] = ()  # x-* keys + nested binding keys (retry/dlq/ordering evidence)


@dataclass(frozen=True, kw_only=True)
class AsyncApiOperation(Model):
    """One operation. `action` is normalized (send|receive)."""

    location: SourceLocation
    pointer: str
    name: str
    action: AsyncAction
    channel_pointer: str | None = None
    message_pointers: tuple[str, ...] = ()
    bindings: tuple[str, ...] = ()
    markers: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AsyncApiMessage(Model):
    location: SourceLocation
    pointer: str
    name: str | None = None
    correlation_id_location: str | None = None
    payload_ref: str | None = None
    payload_shape: str | None = None
    payload_content: object = None
    content_type: str | None = None
    bindings: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AsyncApiSchema(Model):
    location: SourceLocation
    pointer: str
    name: str
    content: object = None


@dataclass(frozen=True, kw_only=True)
class AsyncApiServer(Model):
    location: SourceLocation
    pointer: str
    name: str
    host: str | None = None
    protocol: str | None = None


@dataclass(frozen=True, kw_only=True)
class AsyncApiSecurityRequirement(Model):
    location: SourceLocation
    pointer: str
    owner_pointer: str
    scheme: str


@dataclass(frozen=True, kw_only=True)
class AsyncApiProjectModel(Model):
    """§20.1: channels, operations, messages, schemas, servers,
    protocol_bindings, security, correlation_ids (recorded on messages)."""

    schema_version: str = ASYNCAPI_MODEL_SCHEMA_VERSION
    documents: tuple[AsyncApiDocument, ...] = ()
    channels: tuple[AsyncApiChannel, ...] = ()
    operations: tuple[AsyncApiOperation, ...] = ()
    messages: tuple[AsyncApiMessage, ...] = ()
    schemas: tuple[AsyncApiSchema, ...] = ()
    servers: tuple[AsyncApiServer, ...] = ()
    security_requirements: tuple[AsyncApiSecurityRequirement, ...] = ()
    issues: tuple[AsyncApiIssue, ...] = ()
