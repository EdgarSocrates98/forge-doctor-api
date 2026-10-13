"""§69-§70 capability engine + §130 capability packs.

Detection is evidence-bearing: a `DetectedCapability` exists only when a
loaded model supplied evidence for it — never inferred from a platform
name. §130 capability packs declare what a platform *can* do; they do
not claim what a project *does*.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.asyncapi.model import AsyncApiProjectModel
from forge_doctor_api.analyzers.graphql.model import (
    GraphQLOperationKind,
    GraphQLProjectModel,
)
from forge_doctor_api.analyzers.grpc.model import (
    GrpcProjectModel,
    StreamingMode,
)
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.core.models import (
    Evidence,
    EvidenceKind,
    Model,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.reliability.model import (
    ApiReliabilityModel,
    IdempotencyVerdict,
)
from forge_doctor_api.security.model import ApiSecurityModel, AuthSchemeType


class Capability(StrEnum):
    """§69 detectable capabilities."""

    OPENAPI_32 = "OPENAPI_32"
    GRAPHQL_SUBSCRIPTIONS = "GRAPHQL_SUBSCRIPTIONS"
    GRPC_STREAMING = "GRPC_STREAMING"
    MTLS = "MTLS"
    RATE_LIMITING = "RATE_LIMITING"
    RETRY = "RETRY"
    HEDGING = "HEDGING"
    HEALTH_CHECK = "HEALTH_CHECK"
    ASYNCAPI = "ASYNCAPI"
    WEBHOOK = "WEBHOOK"
    IDEMPOTENCY_KEYS = "IDEMPOTENCY_KEYS"
    IDEMPOTENT_OPERATION = "IDEMPOTENT_OPERATION"
    HEALTH_SERVICE = "HEALTH_SERVICE"
    GRPC_CLIENT = "GRPC_CLIENT"


class DependencyRule(StrEnum):
    """§70 named dependency rules — `requires` maps to a `Capability`."""

    SAFE_RETRY = "SAFE_RETRY"
    GRPC_CLIENT_HEALTH = "GRPC_CLIENT_HEALTH"


@dataclass(frozen=True, kw_only=True)
class CapabilityDependency(Model):
    """§70 `rule` gaps when `trigger` is detected without `requires`."""

    rule: DependencyRule
    trigger: Capability
    requires: Capability
    detail: str


DEPENDENCIES: tuple[CapabilityDependency, ...] = (
    CapabilityDependency(
        rule=DependencyRule.SAFE_RETRY,
        trigger=Capability.RETRY,
        requires=Capability.IDEMPOTENT_OPERATION,
        detail="retry policy without idempotent-operation evidence",
    ),
    CapabilityDependency(
        rule=DependencyRule.GRPC_CLIENT_HEALTH,
        trigger=Capability.GRPC_CLIENT,
        requires=Capability.HEALTH_SERVICE,
        detail="grpc client calls without health-service evidence",
    ),
)


@dataclass(frozen=True, kw_only=True)
class DetectedCapability(Model):
    capability: Capability
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CapabilityGap(Model):
    """§70 dependency shortfall — candidate level, never a verdict."""

    rule: DependencyRule
    capability: Capability
    missing: Capability
    detail: str
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CapabilityReport(Model):
    capabilities: tuple[DetectedCapability, ...] = ()
    gaps: tuple[CapabilityGap, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


def _ev(
    loc: SourceLocation | None,
    summary: str,
    kind: EvidenceKind = EvidenceKind.STATIC,
) -> Evidence:
    return Evidence(
        kind=kind,
        source=loc.path if loc is not None else "unknown",
        summary=summary,
        line=loc.line if loc is not None else None,
    )


def _cap(
    cap: Capability, *evidence: Evidence
) -> DetectedCapability | None:
    return (
        DetectedCapability(capability=cap, evidence=tuple(evidence))
        if evidence
        else None
    )


def detect_capabilities(
    *,
    openapi: OpenApiProjectModel | None = None,
    graphql: GraphQLProjectModel | None = None,
    grpc: GrpcProjectModel | None = None,
    asyncapi: AsyncApiProjectModel | None = None,
    reliability: ApiReliabilityModel | None = None,
    security: ApiSecurityModel | None = None,
) -> CapabilityReport:
    """§69: capability presence is *detected* from evidence, not declared."""
    found: list[DetectedCapability] = []

    if openapi is not None:
        if c := _cap(
            Capability.OPENAPI_32,
            *(
                _ev(doc.location, "OpenAPI 3.2 document")
                for doc in openapi.documents
                if doc.version_family == "3.2"
            ),
        ):
            found.append(c)
        if c := _cap(
            Capability.WEBHOOK,
            *(_ev(w.location, f"webhook {w.name}") for w in openapi.webhooks),
        ):
            found.append(c)
    if graphql is not None and (
        c := _cap(
            Capability.GRAPHQL_SUBSCRIPTIONS,
            *(
                _ev(t.location, f"subscription root {t.name}")
                for t in graphql.types
                if t.operation_root is GraphQLOperationKind.SUBSCRIPTION
            ),
        )
    ):
        found.append(c)
    if grpc is not None:
        if c := _cap(
            Capability.GRPC_STREAMING,
            *(
                _ev(m.location, f"{svc.name}.{m.name} {m.streaming.value}")
                for svc in grpc.services
                for m in svc.methods
                if m.streaming is not StreamingMode.UNARY
            ),
        ):
            found.append(c)
        if c := _cap(
            Capability.HEDGING,
            *(
                _ev(c2.location, "grpc hedging config", EvidenceKind.CONFIG)
                for c2 in grpc.service_configs
                if c2.has_hedging
            ),
        ):
            found.append(c)
        if c := _cap(
            Capability.HEALTH_SERVICE,
            *(
                _ev(
                    c2.location,
                    "grpc health-check config",
                    EvidenceKind.CONFIG,
                )
                for c2 in grpc.service_configs
                if c2.has_health_check
            ),
        ):
            found.append(c)
        if c := _cap(
            Capability.GRPC_CLIENT,
            *(
                _ev(c2.location, f"grpc stub call {c2.stub}")
                for c2 in grpc.client_calls
            ),
        ):
            found.append(c)
    if asyncapi is not None and asyncapi.documents and (
        c := _cap(
            Capability.ASYNCAPI,
            *(
                _ev(doc.location, "AsyncAPI document")
                for doc in asyncapi.documents
            ),
        )
    ):
        found.append(c)
    if reliability is not None:
        if c := _cap(
            Capability.RETRY,
            *(ev for p in reliability.retry_policies for ev in p.evidence),
        ):
            found.append(c)
        if c := _cap(
            Capability.HEALTH_CHECK,
            *(ev for h in reliability.health_checks for ev in h.evidence),
        ):
            found.append(c)
        idem_ev = tuple(
            ev for i in reliability.idempotency for s in i.sources for ev in s.evidence
        )
        idem_ok = tuple(
            i for i in reliability.idempotency
            if i.verdict is IdempotencyVerdict.IDEMPOTENT
        )
        if idem_ok and idem_ev:
            found.append(DetectedCapability(
                capability=Capability.IDEMPOTENT_OPERATION,
                evidence=idem_ev,
            ))
        key_ev = tuple(
            ev for i in reliability.idempotency
            if any(s.kind == "idempotency_key" for s in i.sources)
            for s in i.sources for ev in s.evidence
        )
        if key_ev:
            found.append(DetectedCapability(
                capability=Capability.IDEMPOTENCY_KEYS,
                evidence=key_ev,
            ))
    if security is not None:
        if c := _cap(
            Capability.MTLS,
            *(
                ev for s in security.auth_schemes
                if s.type is AuthSchemeType.MTLS for ev in s.evidence
            ),
        ):
            found.append(c)
        if c := _cap(
            Capability.RATE_LIMITING,
            *(ev for r in security.rate_limits for ev in r.evidence),
        ):
            found.append(c)
        if c := _cap(
            Capability.WEBHOOK,
            *(ev for w in security.webhooks for ev in w.evidence),
        ):
            found.append(c)

    found.sort(key=lambda c: c.capability.value)
    present = {c.capability for c in found}
    gaps = tuple(
        CapabilityGap(
            rule=dep.rule,
            capability=dep.trigger,
            missing=dep.requires,
            detail=dep.detail,
            unknowns=(
                UnknownFact(
                    subject=dep.trigger.value,
                    missing=f"{dep.requires.value} evidence",
                    resolution="the dependency may be satisfied by "
                    "evidence this scan did not see",
                ),
            ),
        )
        for dep in DEPENDENCIES
        if dep.trigger in present and dep.requires not in present
    )
    return CapabilityReport(capabilities=tuple(found), gaps=gaps)


def pack_capabilities(platform: str) -> tuple[str, ...]:
    """§130: what a *named* platform is known to support — reference data."""
    from forge_doctor_api.knowledge.loader import domain_packs

    needle = platform.lower().replace("_", "-").replace(" ", "-")
    for pack in (*domain_packs("frameworks"), *domain_packs("gateways")):
        for entry in pack.entries:
            pid = str(entry.fields.get("platform", "")).lower()
            if pid == needle:
                return tuple(
                    str(c) for c in entry.fields.get("capabilities", ())
                )
    return ()
