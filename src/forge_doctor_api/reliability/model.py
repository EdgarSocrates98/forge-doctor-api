"""Reliability model types (§39-47, §156-158).

Every field carries the evidence it was derived from; absence of
declared config means `None`, never an assumed default (§41, §102).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import (
    Evidence,
    Model,
    SourceLocation,
    UnknownFact,
)

RELIABILITY_MODEL_SCHEMA_VERSION = "reliability-model/1"


@dataclass(frozen=True, kw_only=True)
class RetryPolicy(Model):
    """§40 declared retry policy at one scope."""

    scope: str
    max_attempts: int | None = None
    backoff: str | None = None
    jitter: bool | None = None
    retryable_statuses: tuple[str, ...] = ()
    timeout_ms: float | None = None
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class TimeoutConfig(Model):
    """Declared timeout/deadline at one scope."""

    scope: str
    timeout_ms: float | None = None
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CircuitBreakerConfig(Model):
    """§45 declared circuit-breaker config evidence."""

    scope: str
    provider: str  # resilience4j | envoy | app-config
    failure_threshold: float | None = None
    location: SourceLocation | None = None
    evidence: tuple[Evidence, ...] = ()


class LoadBalancingKind(StrEnum):
    ROUND_ROBIN = "round_robin"
    LEAST_REQUEST = "least_request"
    PICK_FIRST = "pick_first"
    WEIGHTED = "weighted"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class LoadBalancing(Model):
    """§156 declared load-balancing policy."""

    scope: str
    kind: LoadBalancingKind = LoadBalancingKind.UNKNOWN
    detail: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class HealthCheckEvidence(Model):
    """§157 health-check evidence; gRPC standard protocol recognized."""

    scope: str
    protocol: str  # grpc-health-v1 | http | tcp | custom
    endpoint: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class GracefulShutdownEvidence(Model):
    """§158 graceful-shutdown configuration evidence."""

    scope: str
    signal: str | None = None
    drain_seconds: float | None = None
    evidence: tuple[Evidence, ...] = ()


class IdempotencyVerdict(StrEnum):
    IDEMPOTENT = "IDEMPOTENT"
    NON_IDEMPOTENT = "NON_IDEMPOTENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class IdempotencySource(Model):
    """One §42 idempotency evidence source.

    `supports` is None when the source is present but silent on
    idempotency; HTTP method alone never asserts a verdict.
    """

    kind: str  # http_method | idempotency_key | framework_config |
    #          handler_semantics | db_uniqueness | contract_metadata
    detail: str
    supports: bool | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class IdempotencyEvidence(Model):
    """§42 aggregated idempotency evidence for one operation."""

    subject: str
    sources: tuple[IdempotencySource, ...] = ()
    verdict: IdempotencyVerdict = IdempotencyVerdict.UNKNOWN
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiServiceObjective(Model):
    """§46 declared SLO: metric + target + window."""

    name: str
    metric: str  # availability | latency | error_rate | throughput | freshness
    target: float
    comparator: str = ">="  # availability uses >=, error_rate uses <=
    window: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ErrorBudget(Model):
    """§47 error budget; emitted only with sufficient data."""

    objective: str
    window: str
    total: int
    consumed: float
    remaining: float
    sufficient: bool = True
    unknowns: tuple[UnknownFact, ...] = ()


class MeshReliabilityAdapter(ABC):
    """Reserved §73 seam for service-mesh config sources.

    No implementation ships in this spec - mesh adapters plug into
    `load_reliability_model` when they exist.
    """

    name: str

    @abstractmethod
    def detect(self, path: str, head: bytes) -> bool:
        """Strong-marker detection on config text."""


@dataclass(frozen=True, kw_only=True)
class ApiReliabilityModel(Model):
    """§39 aggregated reliability evidence for a project."""

    retry_policies: tuple[RetryPolicy, ...] = ()
    timeouts: tuple[TimeoutConfig, ...] = ()
    circuit_breakers: tuple[CircuitBreakerConfig, ...] = ()
    load_balancing: tuple[LoadBalancing, ...] = ()
    health_checks: tuple[HealthCheckEvidence, ...] = ()
    shutdown_evidence: tuple[GracefulShutdownEvidence, ...] = ()
    idempotency: tuple[IdempotencyEvidence, ...] = ()
    objectives: tuple[ApiServiceObjective, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
