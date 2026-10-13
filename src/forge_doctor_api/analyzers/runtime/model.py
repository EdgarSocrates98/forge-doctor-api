"""Runtime evidence models (§30-32, §84)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    UnknownFact,
)

RUNTIME_MODEL_SCHEMA_VERSION = "runtime-model/1"


class SpanStatus(StrEnum):
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class SpanKind(StrEnum):
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


@dataclass(frozen=True, kw_only=True)
class Span(Model):
    """§32 span model. `evidence` links back to the source artifact."""

    service: str
    operation: str
    parent_id: str | None = None
    span_id: str | None = None
    trace_id: str | None = None
    start_unix_nano: int | None = None
    duration_ms: float | None = None
    status: SpanStatus = SpanStatus.UNSET
    kind: SpanKind = SpanKind.INTERNAL
    attributes: dict[str, str] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RequestSummary(Model):
    """One access-log line normalized to a request summary."""

    method: str | None
    path: str | None
    status: int | None
    duration_ms: float | None = None
    request_id: str | None = None
    trace_id: str | None = None
    bytes_sent: int | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class TraceModel(Model):
    """§31 trace model — summary-first (§173); spans optional."""

    trace_id: str
    spans: tuple[Span, ...] = ()
    root_service: str | None = None
    duration_ms: float | None = None
    critical_path: tuple[str, ...] = ()
    errors: int = 0
    attributes: dict[str, str] = field(default_factory=dict)
    span_count: int = 0
    incomplete: bool = False
    unknowns: tuple[UnknownFact, ...] = ()


class ObservabilitySignal(StrEnum):
    STRUCTURED_LOGS = "structured_logs"
    METRICS = "metrics"
    TRACING = "tracing"
    CORRELATION_IDS = "correlation_ids"
    REQUEST_IDS = "request_ids"
    TRACE_PROPAGATION = "trace_propagation"


@dataclass(frozen=True, kw_only=True)
class ApiObservabilityModel(Model):
    """§84 observability evidence aggregation."""

    signals: dict[str, int] = field(default_factory=dict)
    correlation_keys: tuple[str, ...] = ()
    operation_names: tuple[str, ...] = ()
    error_spans_without_context: int = 0
    spans_without_duration: int = 0
    orphan_spans: int = 0
    request_count: int = 0
    span_count: int = 0
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
