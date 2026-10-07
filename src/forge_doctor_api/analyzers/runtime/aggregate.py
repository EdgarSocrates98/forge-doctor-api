"""§20/§89 online runtime aggregation over execution streams.

`aggregate_executions` consumes an *iterator* of `RequestExecution`
(same objects `run_perf_checks` sees) and emits frozen summary models —
per-(service, operation) latency percentiles, error rates, observed
retry/fanout/payload/downstream-call stats, and SLO-window counters.

Exact while a metric's sample count stays under `cap`; past the cap a
deterministic reservoir (seeded RNG — same input, same sample) keeps
the estimate unbiased and the model reports `approximate=True` plus
the cap used. Nothing is silently rounded.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.analyzers.runtime.history import window_key
from forge_doctor_api.analyzers.runtime.model import RequestSummary
from forge_doctor_api.core.models import Model
from forge_doctor_api.perf.stats import percentile

DEFAULT_SAMPLE_CAP = 50_000


@dataclass(frozen=True, kw_only=True)
class PercentileStats(Model):
    """Percentile summary; `approximate` when the cap was hit."""

    count: int
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    min: float | None = None
    max: float | None = None
    approximate: bool = False
    cap: int | None = None


class _Reservoir:
    """Bounded deterministic sample (Algorithm R, fixed seed)."""

    __slots__ = ("_rng", "cap", "n", "values")

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.n = 0
        self.values: list[float] = []
        self._rng = random.Random(0)

    def add(self, x: float) -> None:
        self.n += 1
        if len(self.values) < self.cap:
            self.values.append(x)
            return
        j = self._rng.randrange(self.n)
        if j < self.cap:
            self.values[j] = x

    @property
    def approximate(self) -> bool:
        return self.n > self.cap

    def stats(self) -> PercentileStats:
        xs = self.values
        return PercentileStats(
            count=self.n,
            p50=percentile(xs, 50),
            p95=percentile(xs, 95),
            p99=percentile(xs, 99),
            min=min(xs) if xs else None,
            max=max(xs) if xs else None,
            approximate=self.approximate,
            cap=self.cap if self.approximate else None,
        )


@dataclass(frozen=True, kw_only=True)
class OperationAggregate(Model):
    """Aggregates for one (service, operation) pair."""

    service: str | None
    operation: str
    requests: int
    errors: int
    error_rate: float | None
    timeouts: int
    retries_observed: int
    retry_rate: float | None
    downstream_calls: int
    fanout_per_request: float | None
    latency_ms: PercentileStats
    request_bytes: PercentileStats
    response_bytes: PercentileStats
    windows: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, kw_only=True)
class RuntimeAggregates(Model):
    """Whole-stream runtime aggregation result."""

    executions: int
    operations: tuple[OperationAggregate, ...]
    approximate: bool = False


@dataclass
class _OpAcc:
    requests: int = 0
    errors: int = 0
    timeouts: int = 0
    retries_observed: int = 0
    downstream_calls: int = 0
    latency: _Reservoir = field(
        default_factory=lambda: _Reservoir(DEFAULT_SAMPLE_CAP))
    request_bytes: _Reservoir = field(
        default_factory=lambda: _Reservoir(DEFAULT_SAMPLE_CAP))
    response_bytes: _Reservoir = field(
        default_factory=lambda: _Reservoir(DEFAULT_SAMPLE_CAP))
    windows: dict[str, int] = field(
        default_factory=lambda: defaultdict(int))


def aggregate_executions(
    executions: Iterable[RequestExecution],
    *,
    cap: int = DEFAULT_SAMPLE_CAP,
) -> RuntimeAggregates:
    """Stream executions -> per-operation aggregate summary."""
    accs: dict[tuple[str | None, str], _OpAcc] = {}
    total = 0
    for e in executions:
        total += 1
        key = (e.service, e.operation)
        acc = accs.get(key)
        if acc is None:
            acc = _OpAcc(
                latency=_Reservoir(cap),
                request_bytes=_Reservoir(cap),
                response_bytes=_Reservoir(cap),
            )
            accs[key] = acc
        acc.requests += 1
        if e.status is not None and (
            e.status == "error" or e.status.startswith("5")
        ):
            acc.errors += 1
        if e.timed_out:
            acc.timeouts += 1
        if e.retries:
            acc.retries_observed += e.retries
        acc.downstream_calls += len(e.downstream_calls)
        if e.duration_ms is not None:
            acc.latency.add(e.duration_ms)
        if e.request_bytes is not None:
            acc.request_bytes.add(float(e.request_bytes))
        if e.response_bytes is not None:
            acc.response_bytes.add(float(e.response_bytes))
        acc.windows[window_key(e.start_unix_nano)] += 1

    operations: list[OperationAggregate] = []
    approximate = False
    for (service, operation), acc in sorted(
        accs.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])
    ):
        approximate = approximate or (
            acc.latency.approximate
            or acc.request_bytes.approximate
            or acc.response_bytes.approximate
        )
        operations.append(
            OperationAggregate(
                service=service,
                operation=operation,
                requests=acc.requests,
                errors=acc.errors,
                error_rate=acc.errors / acc.requests
                if acc.requests
                else None,
                timeouts=acc.timeouts,
                retries_observed=acc.retries_observed,
                retry_rate=acc.retries_observed / acc.requests
                if acc.requests
                else None,
                downstream_calls=acc.downstream_calls,
                fanout_per_request=acc.downstream_calls / acc.requests
                if acc.requests
                else None,
                latency_ms=acc.latency.stats(),
                request_bytes=acc.request_bytes.stats(),
                response_bytes=acc.response_bytes.stats(),
                windows=tuple(sorted(acc.windows.items())),
            )
        )
    return RuntimeAggregates(
        executions=total,
        operations=tuple(operations),
        approximate=approximate,
    )


def aggregate_summaries(
    summaries: Iterable[RequestSummary],
    *,
    cap: int = DEFAULT_SAMPLE_CAP,
) -> tuple[tuple[str, PercentileStats], ...]:
    """Access-log lines -> per-path latency percentiles."""
    accs: dict[str, _Reservoir] = {}
    for r in summaries:
        if r.duration_ms is None:
            continue
        key = r.path or "(unknown)"
        acc = accs.get(key)
        if acc is None:
            acc = _Reservoir(cap)
            accs[key] = acc
        acc.add(r.duration_ms)
    return tuple(
        (path, acc.stats()) for path, acc in sorted(accs.items())
    )
