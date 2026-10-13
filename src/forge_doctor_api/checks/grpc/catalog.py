"""GRPC### check catalog (§27)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Severity,
    check_namespace,
)


@dataclass(frozen=True, kw_only=True)
class GrpcCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    description: str

    @property
    def namespace(self) -> str:
        return check_namespace(self.id)


CATALOG: tuple[GrpcCheckSpec, ...] = (
    GrpcCheckSpec(
        id="GRPC001",
        title="Call without deadline evidence",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="An RPC has no deadline/timeout evidence in service "
        "config or stub calls (§44) — candidate.",
    ),
    GrpcCheckSpec(
        id="GRPC002",
        title="Retry on non-idempotent method candidate",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="A retry policy exists while no idempotency evidence "
        "(idempotency_level option) marks the method safe — candidate.",
    ),
    GrpcCheckSpec(
        id="GRPC003",
        title="Removed proto field not reserved",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A field was removed without a `reserved` statement "
        "covering its number/name.",
    ),
    GrpcCheckSpec(
        id="GRPC004",
        title="Field number reused",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A field number was reused for a different field name "
        "(within a diff, or declared `reserved` overlap).",
    ),
    GrpcCheckSpec(
        id="GRPC005",
        title="Health service absent from declared production config",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="A config file marked production lacks gRPC health "
        "protocol evidence (§157) — candidate.",
    ),
    GrpcCheckSpec(
        id="GRPC006",
        title="Incompatible streaming-mode change",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A method's unary/streaming mode changed between "
        "schema versions (§26).",
    ),
    GrpcCheckSpec(
        id="GRPC007",
        title="Retry-policy amplification risk",
        severity=Severity.MEDIUM,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
        description="Retry and/or hedging policies amplify calls without "
        "deadline evidence — candidate.",
    ),
    # spec 087 — diff-mapped kinds; surface via grpc_breaking_changes
    # through _CHECK_KINDS in checks/grpc/engine.py
    GrpcCheckSpec(
        id="GRPC008",
        title="Enum value renumbered",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="An enum value kept its name but changed number — "
        "wire payloads silently rebind to a different meaning.",
    ),
    GrpcCheckSpec(
        id="GRPC009",
        title="Oneof member changed",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        description="A field entered or left a oneof, or a oneof member "
        "was added/removed — variants decoders may match exhaustively.",
    ),
)

BY_ID: dict[str, GrpcCheckSpec] = {c.id: c for c in CATALOG}
