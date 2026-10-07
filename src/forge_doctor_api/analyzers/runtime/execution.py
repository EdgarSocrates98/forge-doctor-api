"""RequestExecution / DownstreamCall normalization (§28, §29).

Read-only over spec 014 outputs: `TraceModel` spans and access-log
`RequestSummary` records normalize into per-request execution records.
Missing fields stay `None` + `UnknownFact` — never fabricated (§1).
`retries` is the *observed* resend count only; configured retry policy is
a separate fact surface (spec 017) and is never conflated here.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.analyzers.runtime.model import (
    RequestSummary,
    Span,
    SpanKind,
    SpanStatus,
    TraceModel,
)
from forge_doctor_api.core.models import (
    Evidence,
    Model,
    UnknownFact,
)

EXECUTION_MODEL_SCHEMA_VERSION = "request-execution/1"

_REQUEST_ID_KEYS = (
    "x-request-id",
    "x-correlation-id",
    "request_id",
    "http.request.header.x-request-id",
)
_RETRY_KEYS = ("http.resend_count", "retry.count", "grpc.retries")
_ATTEMPT_KEYS = ("x-envoy-attempt-count", "upstream_attempt")
_CACHE_KEYS = ("http.cache_status", "x-cache", "cache.status")
_METHOD_KEYS = ("http.request.method", "http.method")
_REQ_BYTES_KEYS = ("http.request.body.size", "http.request_content_length")
_RESP_BYTES_KEYS = ("http.response.body.size", "http.response_content_length")
_STATUS_KEYS = ("http.status_code", "http.response.status_code")
_TIMEOUT_ERROR_KEYS = ("error.type", "otel.status_description", "error.message")
_TIMEOUT_STATUSES = {"408", "504"}
_CALLEE_KEYS = (
    "peer.service",
    "server.address",
    "rpc.service",
    "http.host",
    "db.system",
    "messaging.destination",
)


@dataclass(frozen=True, kw_only=True)
class DownstreamCall(Model):
    """§29 observed downstream call — all fields runtime-observed."""

    caller: str | None
    callee: str | None
    operation: str
    duration_ms: float | None = None
    status: SpanStatus = SpanStatus.UNSET
    timeout_ms: float | None = None
    retries: int | None = None
    protocol: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RequestExecution(Model):
    """§28 normalized per-request record (summary level, §173)."""

    request_id: str | None
    trace_id: str | None
    service: str | None
    operation: str
    method: str | None = None
    route: str | None = None
    start_unix_nano: int | None = None
    duration_ms: float | None = None
    status: str | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    retries: int | None = None
    downstream_calls: tuple[DownstreamCall, ...] = ()
    cache_status: str | None = None
    timed_out: bool | None = None
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


def _first(attrs: dict[str, str], keys: tuple[str, ...]) -> str | None:
    lower = {k.lower(): v for k, v in attrs.items()}
    for k in keys:
        if k in lower:
            return lower[k]
    return None


def _observed_retries(attrs: dict[str, str]) -> int | None:
    """Resends actually seen — distinct from any configured retry policy."""
    direct = _first(attrs, _RETRY_KEYS)
    if direct is not None:
        try:
            return max(0, int(direct))
        except ValueError:
            return None
    attempts = _first(attrs, _ATTEMPT_KEYS)
    if attempts is not None:
        try:
            return max(0, int(attempts) - 1)
        except ValueError:
            return None
    return None


def _protocol(attrs: dict[str, str], kind: SpanKind) -> str | None:
    if attrs.get("rpc.system"):
        return attrs["rpc.system"]
    if attrs.get("messaging.system"):
        return attrs["messaging.system"]
    if attrs.get("network.protocol.name"):
        name = attrs["network.protocol.name"]
        ver = attrs.get("network.protocol.version")
        return f"{name}/{ver}" if ver else name
    if kind is SpanKind.CLIENT and (
        "http.url" in attrs or "http.route" in attrs or "url.full" in attrs
    ):
        return "http"
    return None


def _span_status(s: Span) -> str | None:
    code = _first(s.attributes, _STATUS_KEYS)
    if code is not None:
        return code
    if s.status is SpanStatus.ERROR:
        return "error"
    if s.status is SpanStatus.OK:
        return "ok"
    return None


def _timed_out(s: Span) -> bool | None:
    """True only on observed timeout evidence; None when nothing recorded."""
    code = _first(s.attributes, _STATUS_KEYS)
    err = _first(s.attributes, _TIMEOUT_ERROR_KEYS)
    if code is None and err is None:
        return None
    return code in _TIMEOUT_STATUSES or (
        err is not None
        and any(k in err.lower() for k in ("timeout", "deadline", "timed out"))
    )


def _downstream_call(s: Span, caller: str | None) -> DownstreamCall:
    return DownstreamCall(
        caller=caller,
        callee=_first(s.attributes, _CALLEE_KEYS),
        operation=s.operation,
        duration_ms=s.duration_ms,
        status=s.status,
        timeout_ms=None,
        retries=_observed_retries(s.attributes),
        protocol=_protocol(s.attributes, s.kind),
        evidence=s.evidence,
    )


def executions_for_trace(
    trace_id: str, spans: list[Span]
) -> tuple[list[RequestExecution], list[UnknownFact]]:
    """One trace's spans -> executions (server/root spans) + unknowns.

    Shared by `executions_from_traces` (kept-span callers) and the
    streaming loader path, which emits executions while spans are still
    in hand so `keep_spans=False` never starves downstream checks.
    """
    if not spans:
        return [], []
    unknowns: list[UnknownFact] = []
    executions: list[RequestExecution] = []
    by_id: dict[str, Span] = {}
    dup_ids: set[str] = set()
    for s in spans:
        if not s.span_id:
            continue
        if s.span_id in by_id:
            dup_ids.add(s.span_id)
        else:
            by_id[s.span_id] = s
    if dup_ids:
        unknowns.append(
            UnknownFact(
                subject=f"trace {trace_id}",
                missing="unique span ids",
                resolution=f"span id(s) {sorted(dup_ids)} appear more "
                "than once; parent attribution used the first",
            )
        )
    servers = [s for s in spans if s.kind is SpanKind.SERVER]
    roots = (
        servers
        if servers
        else [s for s in spans if not s.parent_id][:1]
    )
    # Identity-keyed: span ids can collide across merged exports.
    exec_index: dict[int, int] = {}
    exec_span_ids: set[str] = set()
    pairs: list[tuple[Span, RequestExecution]] = []

    for s in roots:
        pairs.append(
            (
                s,
                RequestExecution(
                    request_id=_first(s.attributes, _REQUEST_ID_KEYS),
                    trace_id=s.trace_id,
                    service=s.service,
                    operation=s.operation,
                    method=_first(s.attributes, _METHOD_KEYS),
                    route=s.attributes.get("http.route") or s.operation,
                    start_unix_nano=s.start_unix_nano,
                    duration_ms=s.duration_ms,
                    status=_span_status(s),
                    request_bytes=_int_attr(s, _REQ_BYTES_KEYS),
                    response_bytes=_int_attr(s, _RESP_BYTES_KEYS),
                    retries=_observed_retries(s.attributes),
                    cache_status=_first(s.attributes, _CACHE_KEYS),
                    timed_out=_timed_out(s),
                    evidence=s.evidence,
                ),
            )
        )
        exec_index[id(s)] = len(pairs) - 1
        if s.span_id:
            exec_span_ids.add(s.span_id)

    calls_by_exec: dict[int, list[DownstreamCall]] = {}
    for s in spans:
        if s.kind not in (SpanKind.CLIENT, SpanKind.PRODUCER):
            continue
        owner_span = _nearest_exec(s, by_id, exec_span_ids)
        owner = (
            exec_index.get(id(owner_span)) if owner_span is not None else None
        )
        if owner is None and pairs:
            owner = 0
            unknowns.append(
                UnknownFact(
                    subject=f"span {s.span_id or '?'}",
                    missing="a parent chain to a server span",
                    resolution="call attributed to the trace root "
                    "execution; parent tree is incomplete",
                )
            )
        if owner is not None:
            caller = by_id.get(s.parent_id or "")
            calls_by_exec.setdefault(owner, []).append(
                _downstream_call(
                    s, caller.service if caller else None
                )
            )

    for idx, (_span_obj, ex) in enumerate(pairs):
        calls = tuple(
            sorted(
                calls_by_exec.get(idx, ()),
                key=lambda c: (c.operation, c.callee or ""),
            )
        )
        executions.append(_with_calls(ex, calls))
    return executions, unknowns


def executions_from_traces(
    traces: tuple[TraceModel, ...],
) -> tuple[tuple[RequestExecution, ...], tuple[UnknownFact, ...]]:
    """Span tree -> one execution per SERVER span (or tree root fallback).

    CLIENT/PRODUCER spans become `DownstreamCall`s attached to the nearest
    ancestor that produced an execution; broken parent chains attach to the
    trace's first execution with an `UnknownFact` instead of guessing.
    """
    executions: list[RequestExecution] = []
    unknowns: list[UnknownFact] = []

    for trace in traces:
        spans = list(trace.spans)
        if not spans:
            continue
        exs, unknown = executions_for_trace(trace.trace_id, spans)
        executions.extend(exs)
        unknowns.extend(unknown)

    executions.sort(
        key=lambda e: (
            e.start_unix_nano or 0,
            e.request_id or "",
            e.trace_id or "",
            e.service or "",
            e.operation,
        )
    )
    return tuple(executions), tuple(unknowns)


def _with_calls(
    ex: RequestExecution, calls: tuple[DownstreamCall, ...]
) -> RequestExecution:
    return RequestExecution(
        request_id=ex.request_id,
        trace_id=ex.trace_id,
        service=ex.service,
        operation=ex.operation,
        method=ex.method,
        route=ex.route,
        start_unix_nano=ex.start_unix_nano,
        duration_ms=ex.duration_ms,
        status=ex.status,
        request_bytes=ex.request_bytes,
        response_bytes=ex.response_bytes,
        retries=ex.retries,
        downstream_calls=calls,
        cache_status=ex.cache_status,
        timed_out=ex.timed_out,
        evidence=ex.evidence,
        unknowns=ex.unknowns,
    )


def _nearest_exec(
    span: Span,
    by_id: dict[str, Span],
    exec_span_ids: set[str],
) -> Span | None:
    seen: set[str] = set()
    node = span
    while node.parent_id and node.parent_id not in seen:
        seen.add(node.parent_id)
        parent = by_id.get(node.parent_id)
        if parent is None:
            return None
        if node.parent_id in exec_span_ids:
            return parent
        node = parent
    return None


def _int_attr(s: Span, keys: tuple[str, ...]) -> int | None:
    v = _first(s.attributes, keys)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def executions_from_summaries(
    summaries: tuple[RequestSummary, ...],
) -> tuple[tuple[RequestExecution, ...], tuple[UnknownFact, ...]]:
    """Access-log lines -> executions; service stays UNKNOWN (§1)."""
    executions: list[RequestExecution] = []
    unknowns: list[UnknownFact] = []
    for r in summaries:
        u: list[UnknownFact] = []
        if r.request_id is None:
            u.append(
                UnknownFact(
                    subject=f"request {r.method} {r.path}",
                    missing="request id / correlation header",
                    resolution="emit a request-id header in the log format",
                )
            )
        u.append(
            UnknownFact(
                subject=f"request {r.method} {r.path}",
                missing="serving service identity",
                resolution="access logs do not name the serving service; "
                "join on trace_id when available",
            )
        )
        unknowns.extend(u)
        executions.append(
            RequestExecution(
                request_id=r.request_id,
                trace_id=r.trace_id,
                service=None,
                operation=r.path or "(unknown)",
                method=r.method,
                route=r.path,
                duration_ms=r.duration_ms,
                status=str(r.status) if r.status is not None else None,
                response_bytes=r.bytes_sent,
                evidence=r.evidence,
                unknowns=tuple(u),
            )
        )
    executions.sort(
        key=lambda e: (
            e.request_id or "",
            e.method or "",
            e.route or "",
            e.status or "",
        )
    )
    return tuple(executions), tuple(unknowns)
