"""gRPC/proto semantic model (§25, §27, §44, §185)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Model,
    SourceLocation,
    UnknownFact,
)

GRPC_MODEL_SCHEMA_VERSION = "grpc-model/1"


class ProtoDocumentStatus(StrEnum):
    PARSED = "PARSED"
    MALFORMED = "MALFORMED"
    NOT_PROTO = "NOT_PROTO"


class ProtoIssueCode(StrEnum):
    MALFORMED = "MALFORMED"
    UNRESOLVED_IMPORT = "UNRESOLVED_IMPORT"


class StreamingMode(StrEnum):
    UNARY = "unary"
    CLIENT_STREAMING = "client_streaming"
    SERVER_STREAMING = "server_streaming"
    BIDI_STREAMING = "bidi_streaming"


@dataclass(frozen=True, kw_only=True)
class ProtoIssue(Model):
    code: ProtoIssueCode
    message: str
    location: SourceLocation | None = None


@dataclass(frozen=True, kw_only=True)
class ProtoField(Model):
    name: str
    type: str
    number: int
    label: str | None = None  # optional|required|repeated|map
    oneof: str | None = None
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ProtoMessage(Model):
    name: str  # qualified: Outer.Inner
    fields: tuple[ProtoField, ...] = ()
    reserved_numbers: tuple[int, ...] = ()
    reserved_names: tuple[str, ...] = ()
    oneofs: tuple[str, ...] = ()
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ProtoEnum(Model):
    name: str
    values: dict[str, int]
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ProtoMethod(Model):
    name: str
    request_type: str
    response_type: str
    streaming: StreamingMode
    idempotent_evidence: tuple[str, ...] = ()
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ProtoService(Model):
    name: str
    package: str
    methods: tuple[ProtoMethod, ...] = ()
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ProtoFile(Model):
    path: str
    syntax: str  # proto2 | proto3
    package: str
    imports: tuple[str, ...] = ()
    unresolved_imports: tuple[str, ...] = ()
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ProtoDocument(Model):
    path: str
    status: ProtoDocumentStatus
    location: SourceLocation | None = None


@dataclass(frozen=True, kw_only=True)
class GrpcRetryPolicy(Model):
    max_attempts: int | None = None
    max_hedges: int | None = None
    initial_backoff: str | None = None
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GrpcClientCall(Model):
    """§185 generated-stub usage evidence."""

    stub: str
    method: str | None
    has_deadline: bool
    has_wait_for_ready: bool
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GrpcServiceConfig(Model):
    """§27 service config / channel-args evidence, per file."""

    path: str
    production: bool = False
    has_health_check: bool = False
    retry_policies: tuple[GrpcRetryPolicy, ...] = ()
    has_hedging: bool = False
    has_load_balancing: bool = False
    has_wait_for_ready: bool = False
    has_keepalive: bool = False
    has_deadline: bool = False
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class GrpcProjectModel(Model):
    schema_version: str = GRPC_MODEL_SCHEMA_VERSION
    documents: tuple[ProtoDocument, ...] = ()
    files: tuple[ProtoFile, ...] = ()
    services: tuple[ProtoService, ...] = ()
    messages: tuple[ProtoMessage, ...] = ()
    enums: tuple[ProtoEnum, ...] = ()
    service_configs: tuple[GrpcServiceConfig, ...] = ()
    client_calls: tuple[GrpcClientCall, ...] = ()
    issues: tuple[ProtoIssue, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
