"""RequestBaseline (§36, §88) — robust stats per dimension window.

Dimensions: service, operation, route, client, dependency. A baseline
with `count < MIN_SAMPLES` is still recorded but marked
`Confidence.UNKNOWN` - regression checks must not fire on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.analyzers.runtime.history import window_key
from forge_doctor_api.core.models import Confidence, Evidence, EvidenceKind, Model
from forge_doctor_api.perf.stats import MIN_SAMPLES, RobustStats, robust_stats


class BaselineDimension(StrEnum):
    SERVICE = "service"
    OPERATION = "operation"
    ROUTE = "route"
    CLIENT = "client"
    DEPENDENCY = "dependency"


@dataclass(frozen=True, kw_only=True)
class RequestBaseline(Model):
    """§36 metrics over one (dimension, key, window) bucket."""

    dimension: BaselineDimension
    key: str
    window: str
    count: int
    latency: RobustStats | None = None
    error_rate: float | None = None
    throughput_per_hour: float | None = None
    retry_rate: float | None = None
    timeout_rate: float | None = None
    payload_p95_bytes: float | None = None
    fanout_mean: float | None = None
    cache_hit_rate: float | None = None
    confidence: Confidence = Confidence.UNKNOWN
    evidence: tuple[Evidence, ...] = ()


def _dim_key(e: RequestExecution, dim: BaselineDimension) -> str | None:
    if dim is BaselineDimension.SERVICE:
        return e.service
    if dim is BaselineDimension.OPERATION:
        return e.operation or None
    if dim is BaselineDimension.ROUTE:
        return e.route
    if dim is BaselineDimension.CLIENT:
        return None  # executions carry no caller-client identity yet
    return None


def _baseline(
    dim: BaselineDimension, key: str, window: str, exs: list[RequestExecution]
) -> RequestBaseline:
    durations = [e.duration_ms for e in exs if e.duration_ms is not None]
    statuses = [e.status for e in exs if e.status is not None]
    errors = sum(
        1
        for s in statuses
        if s == "error" or (s.isdigit() and int(s) >= 500)
    )
    retries = [e.retries for e in exs if e.retries is not None]
    timed = [e.timed_out for e in exs if e.timed_out is not None]
    payloads = [e.response_bytes for e in exs if e.response_bytes is not None]
    fanouts = [float(len(e.downstream_calls)) for e in exs]
    caches = [
        e.cache_status.lower() for e in exs if e.cache_status is not None
    ]
    hits = sum(1 for c in caches if "hit" in c)
    pstats = robust_stats([float(p) for p in payloads])
    return RequestBaseline(
        dimension=dim,
        key=key,
        window=window,
        count=len(exs),
        latency=robust_stats(durations),
        error_rate=errors / len(statuses) if statuses else None,
        throughput_per_hour=float(len(exs)),
        retry_rate=(
            sum(1 for r in retries if r > 0) / len(retries) if retries else None
        ),
        timeout_rate=(
            sum(1 for t in timed if t) / len(timed) if timed else None
        ),
        payload_p95_bytes=pstats.p95 if pstats else None,
        fanout_mean=sum(fanouts) / len(fanouts) if fanouts else None,
        cache_hit_rate=hits / len(caches) if caches else None,
        confidence=(
            Confidence.MEDIUM if len(exs) >= MIN_SAMPLES else Confidence.UNKNOWN
        ),
        evidence=(
            Evidence(
                kind=EvidenceKind.DERIVED,
                source="(runtime-history)",
                summary=f"baseline {dim.value}={key} window={window} n={len(exs)}",
            ),
        ),
    )


def split_windows(
    executions: tuple[RequestExecution, ...],
) -> tuple[list[str], dict[str, list[RequestExecution]]]:
    """Group executions into sorted UTC hour windows."""
    by_window: dict[str, list[RequestExecution]] = {}
    for e in executions:
        by_window.setdefault(window_key(e.start_unix_nano), []).append(e)
    return sorted(by_window), by_window


def build_baselines(
    executions: tuple[RequestExecution, ...],
    dimensions: tuple[BaselineDimension, ...] = (
        BaselineDimension.SERVICE,
        BaselineDimension.OPERATION,
        BaselineDimension.ROUTE,
    ),
) -> tuple[RequestBaseline, ...]:
    """§88 baselines per (dimension, key, window), deterministically ordered."""
    out: list[RequestBaseline] = []
    for dim in dimensions:
        buckets: dict[tuple[str, str], list[RequestExecution]] = {}
        for e in executions:
            key = _dim_key(e, dim)
            if key is None:
                continue
            buckets.setdefault((key, window_key(e.start_unix_nano)), []).append(e)
        for (key, win), exs in buckets.items():
            out.append(_baseline(dim, key, win, exs))
    out.extend(_dependency_baselines(executions))
    out.sort(key=lambda b: (b.dimension.value, b.key, b.window))
    return tuple(out)


def _dependency_baselines(
    executions: tuple[RequestExecution, ...],
) -> list[RequestBaseline]:
    """Per-dependency downstream-call baselines (§88 dependency dim)."""
    buckets: dict[tuple[str, str], list[float]] = {}
    counts: dict[tuple[str, str], int] = {}
    retries: dict[tuple[str, str], list[int]] = {}
    for e in executions:
        win = window_key(e.start_unix_nano)
        for c in e.downstream_calls:
            k = (c.callee or "(unknown)", win)
            if c.duration_ms is not None:
                buckets.setdefault(k, []).append(c.duration_ms)
            counts[k] = counts.get(k, 0) + 1
            if c.retries is not None:
                retries.setdefault(k, []).append(c.retries)
    out: list[RequestBaseline] = []
    for (key, win), durs in buckets.items():
        r = retries.get((key, win), [])
        out.append(
            RequestBaseline(
                dimension=BaselineDimension.DEPENDENCY,
                key=key,
                window=win,
                count=counts.get((key, win), len(durs)),
                latency=robust_stats(durs),
                retry_rate=(
                    sum(1 for x in r if x > 0) / len(r) if r else None
                ),
                confidence=(
                    Confidence.MEDIUM
                    if len(durs) >= MIN_SAMPLES
                    else Confidence.UNKNOWN
                ),
                evidence=(
                    Evidence(
                        kind=EvidenceKind.DERIVED,
                        source="(runtime-history)",
                        summary=f"baseline dependency={key} window={win} "
                        f"n={len(durs)}",
                    ),
                ),
            )
        )
    return out
