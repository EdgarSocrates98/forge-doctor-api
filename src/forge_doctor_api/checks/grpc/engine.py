"""GRPC001-GRPC007 check engine (§27).

Single-model checks (001, 002, 005, 007 + reserved-overlap 004) run on a
`GrpcProjectModel`. Diff checks (003, 004 reuse, 006) run via
`grpc_breaking_changes` through `diff_proto_models` (§26) using the unified
compat classes. Candidates carry UnknownFacts - no runtime guarantees are
asserted from static evidence (§102).
"""

from __future__ import annotations

from forge_doctor_api.analyzers.grpc.compat import diff_proto_models
from forge_doctor_api.analyzers.grpc.model import GrpcProjectModel
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractDiff
from forge_doctor_api.checks.grpc.catalog import BY_ID, GrpcCheckSpec
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    SourceLocation,
    UnknownFact,
)


def _finding(
    spec: GrpcCheckSpec,
    description: str,
    location: SourceLocation,
    *,
    entities: tuple[str, ...] = (),
    unknowns: tuple[UnknownFact, ...] = (),
) -> Finding:
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=EvidenceKind.STATIC,
                source=location.path,
                summary=description,
                line=location.line,
            ),
        ),
        entity_ids=entities,
        source_location=location,
        unknowns=unknowns,
    )


def run_grpc_checks(model: GrpcProjectModel) -> tuple[Finding, ...]:
    """Single-model GRPC checks (001, 002, 005, 007 + within-file 004)."""
    findings: list[Finding] = []

    any_deadline = (
        any(c.has_deadline for c in model.service_configs)
        or any(c.has_deadline for c in model.client_calls)
    )

    # -- GRPC001 call without deadline evidence --------------------------------
    if not any_deadline:
        for svc in model.services:
            for m in svc.methods:
                findings.append(
                    _finding(
                        BY_ID["GRPC001"],
                        f"no deadline/timeout evidence for "
                        f"{svc.package}.{svc.name}/{m.name}",
                        m.location,
                        unknowns=(
                            UnknownFact(
                                subject=f"{svc.name}/{m.name}",
                                missing="deadline or timeout config/code evidence",
                                resolution="service config timeout or stub call "
                                "deadline",
                            ),
                        ),
                    )
                )

    # -- GRPC002 retry on non-idempotent method --------------------------------
    has_retry = any(c.retry_policies or c.has_hedging for c in model.service_configs)
    if has_retry:
        for svc in model.services:
            for m in svc.methods:
                if m.idempotent_evidence:
                    continue
                findings.append(
                    _finding(
                        BY_ID["GRPC002"],
                        f"retry policy exists but {svc.name}/{m.name} has no "
                        f"idempotency evidence",
                        m.location,
                        unknowns=(
                            UnknownFact(
                                subject=f"{svc.name}/{m.name}",
                                missing="idempotency_level option or equivalent "
                                "evidence",
                                resolution="declare `option idempotency_level` in "
                                "proto or confirm handler safety",
                            ),
                        ),
                    )
                )

    # -- GRPC004 within-file: field number collides with `reserved` ------------
    for msg in model.messages:
        reserved = set(msg.reserved_numbers)
        for f in msg.fields:
            if f.number in reserved:
                findings.append(
                    _finding(
                        BY_ID["GRPC004"],
                        f"field number {f.number} on {msg.name}.{f.name} is "
                        f"also listed as reserved",
                        f.location,
                    )
                )

    # -- GRPC005 health service absent from declared production config ---------
    has_health_proto = any(
        "grpc.health.v1" in svc.package or svc.name == "Health"
        for svc in model.services
    )
    for cfg in model.service_configs:
        if cfg.production and not (cfg.has_health_check or has_health_proto):
            findings.append(
                _finding(
                    BY_ID["GRPC005"],
                    f"production config {cfg.path} lacks gRPC health protocol "
                    f"evidence (§157)",
                    cfg.location,
                    unknowns=(
                        UnknownFact(
                            subject="health checks",
                            missing="healthCheckConfig or grpc.health.v1 service "
                            "evidence",
                            resolution="declare health checking in service config",
                        ),
                    ),
                )
            )

    # -- GRPC007 retry amplification risk --------------------------------------
    for cfg in model.service_configs:
        for rp in cfg.retry_policies:
            amplification = (rp.max_attempts or 1) > 1 or cfg.has_hedging
            if amplification and not (cfg.has_deadline or any_deadline):
                findings.append(
                    _finding(
                        BY_ID["GRPC007"],
                        f"retry policy in {cfg.path} (maxAttempts="
                        f"{rp.max_attempts}, hedges={rp.max_hedges}) without "
                        f"deadline evidence — amplification risk",
                        rp.location,
                        unknowns=(
                            UnknownFact(
                                subject="retry amplification",
                                missing="deadline cap + upstream retry evidence",
                                resolution="deadline + upstream retry policy "
                                "visibility",
                            ),
                        ),
                    )
                )
                break
    return tuple(findings)


_CHECK_KINDS = {"GRPC003", "GRPC004", "GRPC006", "GRPC008", "GRPC009"}


def grpc_breaking_changes(
    old: GrpcProjectModel, new: GrpcProjectModel
) -> ContractDiff:
    """Proto schema diff (§26): all changes + findings for check-mapped kinds.

    Every detectable change is a `ContractChange` classified via the
    unified engine; only kinds with dedicated GRPC### ids emit findings.
    """
    changes = diff_proto_models(old, new)
    findings: list[Finding] = []
    for change in changes:
        if change.kind not in _CHECK_KINDS:
            continue
        spec = BY_ID[change.kind]
        confidence = (
            Confidence.UNKNOWN
            if change.classification is CompatibilityClass.UNKNOWN
            else spec.confidence
        )
        findings.append(
            Finding(
                id=spec.id,
                title=spec.title,
                description=change.detail,
                severity=spec.severity,
                confidence=confidence,
                evidence_kind=spec.evidence_kind,
                evidence=(
                    Evidence(
                        kind=EvidenceKind.STATIC,
                        source=change.location.path if change.location else "(proto)",
                        summary=change.detail,
                        line=change.location.line if change.location else None,
                    ),
                ),
                entity_ids=(change.subject,),
                source_location=change.location,
            )
        )
    return ContractDiff(changes=changes, findings=tuple(findings))
