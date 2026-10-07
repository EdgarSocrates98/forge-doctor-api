"""RequestHistory (§87) — compact normalized history storage.

Executions are stored as summary-level records (§172-§173): the
`RequestExecution` already is the normalized summary - no raw trace
bodies are retained. Records are keyed by (service, operation, window)
where window is a UTC hour bucket derived from the execution's own
`start_unix_nano` — data-derived, never wall-clock — so ordering and
windowing are deterministic on any host.

Compaction keeps every normalized field (status/duration/bytes/retries/
downstream calls), so "what changed" queries between windows stay
answerable — nothing is collapsed into opaque counters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from forge_doctor_api.analyzers.runtime.execution import RequestExecution

HOUR_NS = 3_600_000_000_000
UNWINDOWED = "(unwindowed)"


def window_key(start_unix_nano: int | None) -> str:
    """UTC hour bucket `YYYY-MM-DDTHH`, or `(unwindowed)` without a start."""
    if start_unix_nano is None:
        return UNWINDOWED
    dt = datetime.fromtimestamp(start_unix_nano / 1e9, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H")


def _exec_key(e: RequestExecution) -> tuple[str, str, str]:
    return (e.service or "(unknown)", e.operation, window_key(e.start_unix_nano))


def _order_key(e: RequestExecution) -> tuple[int, str, str, str, str]:
    return (
        e.start_unix_nano or 0,
        e.request_id or "",
        e.trace_id or "",
        e.service or "",
        e.operation,
    )


@dataclass
class RequestHistory:
    """§87 compact append/query store keyed by service+operation+window."""

    _records: dict[tuple[str, str, str], list[RequestExecution]]

    def __init__(self) -> None:
        self._records = {}

    def add(self, execution: RequestExecution) -> None:
        self._records.setdefault(_exec_key(execution), []).append(execution)

    def add_all(self, executions: tuple[RequestExecution, ...]) -> None:
        for e in executions:
            self.add(e)

    def keys(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(sorted(self._records))

    def windows(self) -> tuple[str, ...]:
        return tuple(sorted({k[2] for k in self._records}))

    def query(
        self,
        service: str | None = None,
        operation: str | None = None,
        window: str | None = None,
    ) -> tuple[RequestExecution, ...]:
        """Deterministically ordered records matching the given filters."""
        out: list[RequestExecution] = []
        for key in sorted(self._records):
            svc, op, win = key
            if service is not None and svc != service:
                continue
            if operation is not None and op != operation:
                continue
            if window is not None and win != window:
                continue
            out.extend(sorted(self._records[key], key=_order_key))
        return tuple(out)

    def services(self) -> tuple[str, ...]:
        return tuple(sorted({k[0] for k in self._records}))

    def operations(
        self, service: str | None = None
    ) -> tuple[tuple[str, str], ...]:
        pairs = {
            (k[0], k[1])
            for k in self._records
            if service is None or k[0] == service
        }
        return tuple(sorted(pairs))

    def count(self) -> int:
        return sum(len(v) for v in self._records.values())
