"""ApiPerformanceSignal (§33) - observed performance evidence records.

Signals are emitted only where runtime evidence exists; families with
no evidence produce nothing (never fabricated). Regression-flavored
claims live in the APIPERF### checks; this layer reports raw observed
magnitudes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.runtime.execution import RequestExecution
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Model,
)


class PerformanceFamily(StrEnum):
    LATENCY_REGRESSION = "LATENCY_REGRESSION"
    DOWNSTREAM_LATENCY = "DOWNSTREAM_LATENCY"
    QUEUEING = "QUEUEING"
    RETRY_AMPLIFICATION = "RETRY_AMPLIFICATION"
    PAYLOAD_AMPLIFICATION = "PAYLOAD_AMPLIFICATION"
    SERIALIZATION_OVERHEAD = "SERIALIZATION_OVERHEAD"
    CACHE_MISS_PRESSURE = "CACHE_MISS_PRESSURE"
    CONCURRENCY_PRESSURE = "CONCURRENCY_PRESSURE"
    TIMEOUT_PRESSURE = "TIMEOUT_PRESSURE"
    FANOUT_AMPLIFICATION = "FANOUT_AMPLIFICATION"
    N_PLUS_ONE = "N_PLUS_ONE"


@dataclass(frozen=True, kw_only=True)
class ApiPerformanceSignal(Model):
    """One observed performance fact (§33)."""

    family: PerformanceFamily
    subject: str
    magnitude: float | None = None
    detail: str
    confidence: Confidence = Confidence.MEDIUM
    evidence: tuple[Evidence, ...] = ()


def _ev(summary: str) -> tuple[Evidence, ...]:
    return (
        Evidence(kind=EvidenceKind.RUNTIME, source="(runtime)", summary=summary),
    )


def performance_signals(
    executions: tuple[RequestExecution, ...],
) -> tuple[ApiPerformanceSignal, ...]:
    """Evidence-backed §33 signals from normalized executions."""
    out: list[ApiPerformanceSignal] = []

    # RETRY_AMPLIFICATION - observed resends
    retried = [e for e in executions if (e.retries or 0) > 0]
    nested = sum(
        c.retries or 0 for e in executions for c in e.downstream_calls
    )
    if retried or nested:
        out.append(
            ApiPerformanceSignal(
                family=PerformanceFamily.RETRY_AMPLIFICATION,
                subject="(observed)",
                magnitude=float(len(retried) + nested),
                detail=f"{len(retried)} request(s) retried; "
                f"{nested} observed downstream resend(s)",
                evidence=_ev("observed retry counters on executions"),
            )
        )

    # PAYLOAD_AMPLIFICATION - large observed responses
    payloads = sorted(
        e.response_bytes for e in executions if e.response_bytes is not None
    )
    if payloads and payloads[-1] >= 256 * 1024:
        out.append(
            ApiPerformanceSignal(
                family=PerformanceFamily.PAYLOAD_AMPLIFICATION,
                subject="(observed)",
                magnitude=float(payloads[-1]),
                detail=f"largest observed response: {payloads[-1]} bytes",
                confidence=Confidence.LOW,
                evidence=_ev("response_bytes on request executions"),
            )
        )

    # FANOUT_AMPLIFICATION - wide downstream fan-out
    wide = [e for e in executions if len(e.downstream_calls) >= 4]
    if wide:
        out.append(
            ApiPerformanceSignal(
                family=PerformanceFamily.FANOUT_AMPLIFICATION,
                subject="(observed)",
                magnitude=float(max(len(e.downstream_calls) for e in wide)),
                detail=f"{len(wide)} request(s) fan out to >=4 downstreams",
                evidence=_ev("downstream_calls on request executions"),
            )
        )

    # N_PLUS_ONE - repeated calls to the same callee inside one request
    for e in executions:
        counts: dict[str, int] = {}
        for c in e.downstream_calls:
            if c.callee:
                counts[c.callee] = counts.get(c.callee, 0) + 1
        repeated = {k: v for k, v in counts.items() if v >= 3}
        if repeated:
            out.append(
                ApiPerformanceSignal(
                    family=PerformanceFamily.N_PLUS_ONE,
                    subject=e.operation,
                    detail="repeated downstream calls in one request: "
                    + ", ".join(f"{k}x{v}" for k, v in sorted(repeated.items())),
                    confidence=Confidence.LOW,
                    evidence=e.evidence,
                )
            )

    # TIMEOUT_PRESSURE - observed timeouts
    timed = sum(1 for e in executions if e.timed_out)
    if timed:
        out.append(
            ApiPerformanceSignal(
                family=PerformanceFamily.TIMEOUT_PRESSURE,
                subject="(observed)",
                magnitude=float(timed),
                detail=f"{timed} request(s) ended with timeout evidence",
                evidence=_ev("timeout markers on request executions"),
            )
        )

    # CACHE_MISS_PRESSURE - observed misses
    caches = [e.cache_status.lower() for e in executions if e.cache_status]
    misses = sum(1 for c in caches if "miss" in c or "expired" in c)
    if caches and misses:
        out.append(
            ApiPerformanceSignal(
                family=PerformanceFamily.CACHE_MISS_PRESSURE,
                subject="(observed)",
                magnitude=misses / len(caches),
                detail=f"{misses}/{len(caches)} observed cache misses",
                evidence=_ev("cache_status on request executions"),
            )
        )
    return tuple(out)
