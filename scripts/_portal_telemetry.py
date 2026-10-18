# telemetry.py — forge/PortalEvent/1: execution telemetry for the portal.
#
# Lives OUTSIDE forge_portal.py on purpose (same pattern as
# registry_ops.py): the vendored server stays a request/transport layer
# and only learns to EMIT events (PortalServer.emit_event); this module
# is the storage + read side an adapter opts into.
#
# Contract (docs/observability/execution-events.md):
#   - `schema` + `event_type` are the only mandatory keys; `timestamp`
#     is stamped by emit_event at record time — never back-filled for
#     history, never synthesized. Consumers must tolerate absence.
#   - Optional: event_id, correlation_id, trace_id, span_id,
#     parent_span_id, source, target, status, duration_ms, metadata,
#     evidence. All additive — older producers keep working.
#   - Nothing leaves this machine: events live in a bounded in-process
#     buffer; there is no remote sink.
#
# Opt-in (one line in an adapter):
#   self.event_sink = (rec := EventRecorder()).emit
#   self.ops = default_operations(self) + telemetry.operations(rec) + [...]
#
# `PortalServer` picks `adapter.event_sink` up automatically, so every
# op boundary (start/end/refusal/timeout) is recorded for free plus
# the transport refusals (session/origin/rate-limit/confirm…). Domain
# events are emitted by the adapter itself via `ctx.emit(...)`.

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any

import _forge_portal as fp

EVENT_SCHEMA = fp.EVENT_SCHEMA
REPORT_SCHEMA = "forge/PortalEventReport/1"
DEFAULT_CAPACITY = 500

# Closed vocabulary of statuses the portal itself emits; adapters may
# use their own values — consumers render them verbatim.
KNOWN_STATUSES = frozenset(
    {"started", "ok", "refused", "failed", "timeout", "skipped"}
)

# Event types the vendored server emits. Adapter-emitted types are
# free-form (`task.planned`, `mcp.verification`, `tool.invocation`,
# `receipt`, `state.change`, …) — consumers must not assume a closed
# enum, only the field contract.
CORE_EVENT_TYPES = frozenset(
    {"operation.start", "operation.end", "request.rejected"}
)


def _scalarish(value: Any, depth: int = 0) -> Any:
    """Whitelist event payloads to scalars/small containers — same rule
    as `read_registry_state`: events stay data, never objects. Caps
    keep a pathological metadata blob from bloating the buffer."""
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_scalarish(v, depth + 1) for v in value[:200]]
    if isinstance(value, dict):
        return {
            str(k): _scalarish(v, depth + 1)
            for k, v in list(value.items())[:50]
        }
    return str(value)


class EventRecorder:
    """Bounded in-process store of forge/PortalEvent/1 records.

    Thread-safe: op handlers run on the server's worker pool. `emit`
    validates the contract floor (schema/event_type/timestamp present),
    mints `event_id` when the producer did not, keeps insertion order,
    and counts — the counters feed the /metrics projection. Evicted
    events bump `dropped` so reports can mark themselves truncated
    instead of silently pretending completeness."""

    def __init__(self, maxlen: int = DEFAULT_CAPACITY) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0
        self._dropped = 0
        self._counters: dict[str, int] = {}

    # -- write side ----------------------------------------------------
    def emit(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Store one event (already redacted by emit_event). Returns the
        stored record, or None when it fails the contract floor — a
        malformed event is dropped, never repaired into fake data."""
        if not isinstance(event, dict):
            return None
        if event.get("schema") != EVENT_SCHEMA:
            return None
        etype = event.get("event_type")
        if not isinstance(etype, str) or not etype:
            return None
        clean: dict[str, Any] = _scalarish(event)
        with self._lock:
            self._seq += 1
            clean.setdefault("event_id", f"evt-{self._seq}")
            if len(self._events) == self._events.maxlen:
                self._dropped += 1  # the append below evicts the oldest
            self._events.append(clean)
            self._counters[etype] = self._counters.get(etype, 0) + 1
            status = clean.get("status")
            if isinstance(status, str) and status:
                key = f"{etype}.{status}"
                self._counters[key] = self._counters.get(key, 0) + 1
        return clean

    # -- read side -----------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def counters(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def events_for_task(
        self, task_id: str, correlation_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Events that really belong to a task: `metadata.task_id`
        naming the record, or sharing the task's own correlation_id.
        No task_id/correlation match is ever inferred from timing."""
        out: list[dict[str, Any]] = []
        for e in self.snapshot():
            raw_meta: Any = e.get("metadata")
            meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
            if meta.get("task_id") == task_id:
                out.append(e)
                continue
            if correlation_id and e.get("correlation_id") == correlation_id:
                out.append(e)
        return out

    # -- report projections --------------------------------------------
    def report(self, *, forge_id: str | None = None) -> dict[str, Any]:
        """forge/PortalEventReport/1 — the full contract view."""
        events = self.snapshot()
        return {
            "schema": REPORT_SCHEMA,
            "generated_at": fp._utc_now(),
            "forge_id": forge_id,
            "count": len(events),
            "dropped": self.dropped,
            "truncated": self.dropped > 0,
            "capacity": self._events.maxlen,
            "counters": self.counters(),
            "events": events,
        }

    def metrics_report(self) -> dict[str, Any]:
        """MetricsReport projection (forge/PortalApi/1 §5.4) — the field
        names the frontend already consumes. Pure projection of real
        recorded events; `truncated` mirrors the buffer's honesty."""
        events = self.snapshot()
        return {
            "generated_at": fp._utc_now(),
            "counters": self.counters(),
            "events": [self._to_metrics_event(e) for e in events],
            "truncated": self.dropped > 0,
        }

    @staticmethod
    def _to_metrics_event(e: dict[str, Any]) -> dict[str, Any]:
        raw_meta: Any = e.get("metadata")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        return {
            "kind": e.get("event_type"),
            "at": e.get("timestamp"),
            "duration_ms": e.get("duration_ms"),
            "status": e.get("status") or "recorded",
            "origin": e.get("source") or "portal",
            "correlation_id": e.get("correlation_id"),
            "detail": meta.get("detail") if isinstance(meta.get("detail"), str) else None,
        }


# ---------------------------------------------------------------------------
# ops — compose into an adapter's ops list
# ---------------------------------------------------------------------------


def _events_op(
    recorder: EventRecorder, adapter: fp.PortalAdapter
) -> Callable[[fp.RequestContext], Any]:
    def h(ctx: fp.RequestContext) -> Any:
        report = recorder.report(forge_id=adapter.forge_id)
        # read-only filters over the recorded window only — the adapter
        # never fabricates history the buffer already evicted.
        q = ctx.query
        cid = (q.get("correlation_id") or [""])[0].strip()
        etype = (q.get("type") or [""])[0].strip()
        status = (q.get("status") or [""])[0].strip()
        events = report["events"]
        if cid:
            events = [e for e in events if e.get("correlation_id") == cid]
        if etype:
            events = [e for e in events if e.get("event_type") == etype]
        if status:
            events = [e for e in events if e.get("status") == status]
        try:
            limit = int((q.get("limit") or ["0"])[0])
        except ValueError:
            limit = 0
        if limit > 0:
            events = events[-limit:]
        return {**report, "count": len(events), "events": events}

    return h


def operations(recorder: EventRecorder, adapter: fp.PortalAdapter) -> list[fp.Operation]:
    """`GET /events` (full forge/PortalEvent/1 window) + `GET /metrics`
    (the §5.4 projection the frontend already renders). Both read-only
    over the recorded buffer — empty means "nothing recorded yet",
    absent op means "adapter did not opt in" (UNVERIFIED upstream)."""
    return [
        fp.Operation("GET", "/events", _events_op(recorder, adapter)),
        fp.Operation("GET", "/metrics", lambda ctx: recorder.metrics_report()),
    ]


def task_events_op(
    recorder: EventRecorder, tasks: Callable[[], list[dict[str, Any]]]
) -> fp.Operation:
    """`GET /tasks/{task_id}/events` — the recorded events belonging to
    one task record: `metadata.task_id` matches plus every event sharing
    the task's own correlation_id (both are real links, never timing
    guesses). A task id that matches no record returns an honest empty
    window with `task: None` — consumers distinguish it from a 404."""

    def h(ctx: fp.RequestContext) -> Any:
        task_id = ctx.params["task_id"]
        task = next((t for t in tasks() if t.get("id") == task_id), None)
        cid = task.get("correlation_id") if isinstance(task, dict) else None
        return {
            "schema": REPORT_SCHEMA,
            "task_id": task_id,
            "task": task,
            "events": recorder.events_for_task(task_id, cid),
            "truncated": recorder.dropped > 0,
        }

    return fp.Operation("GET", "/tasks/{task_id}/events", h)
