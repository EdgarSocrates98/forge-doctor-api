"""§110-§115, §190-§191 fleet intelligence models.

Fleet results are aggregations over declared workspace members. Missing
or unscanned repos appear as UNKNOWN entries — never silently excluded.
Complexity signals are opportunities, not errors (§112). There is no
composite health number (§191).
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Evidence, Model, UnknownFact


@dataclass(frozen=True, kw_only=True)
class FleetEntry(Model):
    """One row in a fleet question's answer."""

    repo: str
    subject: str
    detail: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class FleetQuestion(Model):
    """§110 one fleet question with its evidence-bearing answers."""

    key: str
    question: str
    entries: tuple[FleetEntry, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PortfolioMember(Model):
    """§111 one member's portfolio slice."""

    repo: str
    role: str
    styles: tuple[str, ...] = ()  # rest | graphql | grpc | async | gateway
    apis: int = 0               # contract documents
    operations: int = 0
    gateways: int = 0           # declared gateway routes
    external_apis: int = 0
    owner: str | None = None


@dataclass(frozen=True, kw_only=True)
class ComplexitySignal(Model):
    """§112 a complexity pattern — opportunity-level, never an error."""

    kind: str  # multi_protocol | shared_external_dependency | gateway_chain | multiple_auth_models
    detail: str
    subjects: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DeprecationReadiness(Model):
    """§114 readiness view of one deprecated API.

    Numeric fields are None when their evidence source is absent —
    "no client evidence available" is distinct from "0 clients".
    """

    repo: str
    subject: str
    remaining_clients: int | None = None
    remaining_client_subjects: tuple[str, ...] = ()
    observed_traffic: int | None = None
    replacement: str | None = None
    contract_age_days: int | None = None
    sunset_date: str | None = None
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class FleetExternalApi(Model):
    """§115 external dependency view; host sanitized (userinfo/query stripped)."""

    repo: str
    host: str
    operations: tuple[str, ...] = ()
    timeout_ms: float | None = None
    has_retry: bool | None = None
    has_auth: bool | None = None
    owner: str | None = None
    criticality: str | None = None
    signals: tuple[str, ...] = ()  # §116 candidate-level consumption signals
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class QualityDimension(Model):
    """§190 one quality dimension for one repo — evidence, not a score."""

    name: str
    repo: str
    value: str  # e.g. "2/3 operations have operationId" or "unknown"
    evidence: tuple[Evidence, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class FleetHealth(Model):
    """§191 health as counts — never one number."""

    breaking_changes: int = 0
    reliability_gaps: int = 0
    security_candidates: int = 0
    runtime_regressions: int = 0
    unknowns: int = 0


@dataclass(frozen=True, kw_only=True)
class FleetReport(Model):
    """Aggregated workspace view: questions + portfolio + signals."""

    workspace: str
    members_present: tuple[str, ...] = ()
    members_missing: tuple[str, ...] = ()
    questions: tuple[FleetQuestion, ...] = ()
    portfolio: tuple[PortfolioMember, ...] = ()
    complexity: tuple[ComplexitySignal, ...] = ()
    deprecations: tuple[DeprecationReadiness, ...] = ()
    external_apis: tuple[FleetExternalApi, ...] = ()
    quality: tuple[QualityDimension, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
