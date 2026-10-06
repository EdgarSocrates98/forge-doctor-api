"""Capacity intelligence (§91-93): signals, saturation, cost drivers.

Only derivable dimensions produce values; everything else reports
`Saturation.UNKNOWN` with explicit threshold provenance. Cost drivers
report magnitudes, never billing (§93).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.analyzers.runtime.history import window_key
from forge_doctor_api.analyzers.runtime.model import RequestSummary
from forge_doctor_api.core.models import Evidence, EvidenceKind, Model


class Saturation(StrEnum):
    HEALTHY = "HEALTHY"
    ELEVATED = "ELEVATED"
    SATURATED = "SATURATED"
    UNKNOWN = "UNKNOWN"


class CapacityDimension(StrEnum):
    RPS = "rps"
    CONCURRENCY = "concurrency"
    CONNECTION_POOL = "connection_pool"
    THREAD_POOL = "thread_pool"
    EVENT_LOOP = "event_loop"
    CPU = "cpu"
    MEMORY = "memory"
    GATEWAY_CONCURRENCY = "gateway_concurrency"
    QUEUE_DEPTH = "queue_depth"


@dataclass(frozen=True, kw_only=True)
class ThresholdProvenance(Model):
    """Where the saturation thresholds came from (§92)."""

    source: str
    elevated: float | None = None
    saturated: float | None = None


@dataclass(frozen=True, kw_only=True)
class ApiCapacitySignal(Model):
    """§91 one capacity dimension reading."""

    dimension: CapacityDimension
    value: float | None = None
    unit: str | None = None
    saturation: Saturation = Saturation.UNKNOWN
    thresholds: ThresholdProvenance | None = None
    evidence: tuple[Evidence, ...] = ()


class CostDriver(StrEnum):
    REQUEST_COUNT = "request_count"
    COMPUTE_DURATION = "compute_duration"
    PAYLOAD_VOLUME = "payload_volume"
    NETWORK_EGRESS = "network_egress"
    GATEWAY_CALLS = "gateway_calls"
    LOGGING_VOLUME = "logging_volume"
    TRACE_VOLUME = "trace_volume"
    CACHE_STORAGE = "cache_storage"


@dataclass(frozen=True, kw_only=True)
class ApiCostDriver(Model):
    """§93 cost driver magnitude (never a billing number)."""

    driver: CostDriver
    quantity: float
    unit: str
    evidence: tuple[Evidence, ...] = ()


def _classify(
    value: float | None, thresholds: ThresholdProvenance | None
) -> Saturation:
    if value is None or thresholds is None:
        return Saturation.UNKNOWN
    if (
        thresholds.saturated is not None
        and value >= thresholds.saturated
    ):
        return Saturation.SATURATED
    if thresholds.elevated is not None and value >= thresholds.elevated:
        return Saturation.ELEVATED
    return Saturation.HEALTHY


def capacity_signals(
    executions: tuple[RequestExecution, ...],
    thresholds: dict[CapacityDimension, ThresholdProvenance] | None = None,
) -> tuple[ApiCapacitySignal, ...]:
    """§91 capacity signals; non-derivable dimensions stay UNKNOWN."""
    thresholds = thresholds or {}
    out: list[ApiCapacitySignal] = []

    # RPS: requests per hour-window is derivable from executions.
    windows: dict[str, int] = {}
    for e in executions:
        w = window_key(e.start_unix_nano)
        windows[w] = windows.get(w, 0) + 1
    max_rph = max(windows.values()) if windows else None
    rps = (max_rph / 3600.0) if max_rph is not None else None
    tp = thresholds.get(CapacityDimension.RPS)
    out.append(
        ApiCapacitySignal(
            dimension=CapacityDimension.RPS,
            value=rps,
            unit="req/s (peak hour window)",
            saturation=_classify(rps, tp),
            thresholds=tp,
            evidence=(
                Evidence(
                    kind=EvidenceKind.DERIVED,
                    source="(runtime-history)",
                    summary="peak requests within one UTC hour window / 3600",
                ),
            ),
        )
    )

    # CONCURRENCY: max observed fan-out is a weak proxy - flagged as such.
    fanout = max((len(e.downstream_calls) for e in executions), default=None)
    tp = thresholds.get(CapacityDimension.CONCURRENCY)
    out.append(
        ApiCapacitySignal(
            dimension=CapacityDimension.CONCURRENCY,
            value=float(fanout) if fanout is not None else None,
            unit="max observed downstream fan-out",
            saturation=_classify(
                float(fanout) if fanout is not None else None, tp
            ),
            thresholds=tp,
            evidence=(
                Evidence(
                    kind=EvidenceKind.DERIVED,
                    source="(runtime-history)",
                    summary="fan-out proxy only; true concurrency needs "
                    "runtime metrics",
                ),
            ),
        )
    )

    # Everything else needs metric exports we do not ingest.
    for dim in (
        CapacityDimension.CONNECTION_POOL,
        CapacityDimension.THREAD_POOL,
        CapacityDimension.EVENT_LOOP,
        CapacityDimension.CPU,
        CapacityDimension.MEMORY,
        CapacityDimension.GATEWAY_CONCURRENCY,
        CapacityDimension.QUEUE_DEPTH,
    ):
        out.append(
            ApiCapacitySignal(
                dimension=dim,
                saturation=Saturation.UNKNOWN,
                thresholds=thresholds.get(dim),
                evidence=(
                    Evidence(
                        kind=EvidenceKind.DERIVED,
                        source="(runtime-history)",
                        summary=f"no {dim.value} metric evidence in "
                        "ingested artifacts",
                    ),
                ),
            )
        )
    return tuple(out)


def cost_drivers(
    executions: tuple[RequestExecution, ...],
    summaries: tuple[RequestSummary, ...] = (),
) -> tuple[ApiCostDriver, ...]:
    """§93 driver magnitudes from normalized records (not billing)."""
    out: list[ApiCostDriver] = []

    def ev(detail: str) -> tuple[Evidence, ...]:
        return (
            Evidence(
                kind=EvidenceKind.DERIVED,
                source="(runtime-history)",
                summary=detail,
            ),
        )

    n = len(executions)
    if n:
        out.append(
            ApiCostDriver(
                driver=CostDriver.REQUEST_COUNT,
                quantity=float(n),
                unit="requests",
                evidence=ev("normalized request executions"),
            )
        )
    compute = sum(e.duration_ms or 0.0 for e in executions)
    if compute:
        out.append(
            ApiCostDriver(
                driver=CostDriver.COMPUTE_DURATION,
                quantity=compute,
                unit="ms total request duration",
                evidence=ev("sum of observed request durations"),
            )
        )
    egress = sum(e.response_bytes or 0 for e in executions)
    if egress:
        out.append(
            ApiCostDriver(
                driver=CostDriver.NETWORK_EGRESS,
                quantity=float(egress),
                unit="response bytes",
                evidence=ev("sum of observed response_bytes"),
            )
        )
    payload = egress + sum(e.request_bytes or 0 for e in executions)
    if payload:
        out.append(
            ApiCostDriver(
                driver=CostDriver.PAYLOAD_VOLUME,
                quantity=float(payload),
                unit="request+response bytes",
                evidence=ev("sum of observed request/response bytes"),
            )
        )
    if summaries:
        out.append(
            ApiCostDriver(
                driver=CostDriver.LOGGING_VOLUME,
                quantity=float(len(summaries)),
                unit="access-log lines",
                evidence=ev("normalized access-log summaries"),
            )
        )
    return tuple(out)
