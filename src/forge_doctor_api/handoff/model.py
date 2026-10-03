"""§134-§138, §215 handoff and routing models.

Bundles are compact by design (§135): references + summaries, never raw
repository payloads. Cross-domain links are ExternalReferences only —
graphs are never merged (§138).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forge_doctor_api.core.models import (
    Evidence,
    Finding,
    Model,
    UnknownFact,
)
from forge_doctor_api.safefix.model import Remediation


@dataclass(frozen=True, kw_only=True)
class ExternalReference(Model):
    """§138 a reference to an entity owned by another domain.

    `target_ref` is opaque to this domain — the reference declares that a
    handoff point exists, not what the foreign graph looks like.
    """

    source_id: str
    target_domain: str
    target_ref: str
    relation: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiHandoffBundle(Model):
    """§134 compact handoff unit for API Forge / The Forger."""

    schema_version: str = "1.0"
    service: str | None = None
    operations: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    breaking_changes: tuple[str, ...] = ()
    clients_affected: tuple[str, ...] = ()
    runtime_regressions: tuple[str, ...] = ()
    security_candidates: tuple[str, ...] = ()
    reliability_signals: tuple[str, ...] = ()
    external_references: tuple[ExternalReference, ...] = ()
    remediation_candidates: tuple[Remediation, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
    knowledge_versions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ForgerRequest(Model):
    """§136/§215 structured request shape routed by The Forger."""

    task: str
    domain: str = "api"
    subject: str | None = None


@dataclass(frozen=True, kw_only=True)
class ForgerRoute(Model):
    """§215 routing decision — a declared destination, never an execution."""

    domain: str
    handler: str
    reason: str
    chain: tuple[str, ...] = ()
    references: tuple[ExternalReference, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
