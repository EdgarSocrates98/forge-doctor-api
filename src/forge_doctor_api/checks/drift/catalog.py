"""DRIFT### check catalog (§14, §143-§146).

Contract-vs-implementation drift. The engine never picks a source of truth:
`ContractAuthority` config steers severity, and when undeclared every
directional finding carries an `UnknownFact` for the missing authority
(§144-§145).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Confidence, EvidenceKind, Severity

S = Severity
C = Confidence


class ContractAuthority(StrEnum):
    """`contract_authority` policy values (§144). `UNDECLARED` => report
    conflict both directions, never decide (§145)."""

    OPENAPI = "openapi"
    IMPLEMENTATION = "implementation"
    GATEWAY = "gateway"
    NONE = "none"
    UNDECLARED = "undeclared"


@dataclass(frozen=True)
class DriftCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    trigger: str


CATALOG: tuple[DriftCheckSpec, ...] = (
    DriftCheckSpec(
        id="DRIFT001",
        title="Documented operation missing implementation",
        severity=S.HIGH,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger="A contract operation has no discovered route at its method + path.",
    ),
    DriftCheckSpec(
        id="DRIFT002",
        title="Implemented route absent from contract",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger="A discovered route matches no contract operation at its method + path.",
    ),
    DriftCheckSpec(
        id="DRIFT003",
        title="Method mismatch",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "The same normalized path exists in contract and implementation but with "
            "different methods (documented method missing at that path, or route method "
            "undocumented at that path)."
        ),
    ),
    DriftCheckSpec(
        id="DRIFT004",
        title="Parameter mismatch",
        severity=S.MEDIUM,
        confidence=C.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A matched operation/route pair differs in parameters: path-template names, "
            "declared location, or required-ness. MEDIUM confidence — server-side params "
            "with framework defaults may not all be contractual."
        ),
    ),
    DriftCheckSpec(
        id="DRIFT005",
        title="Request schema mismatch",
        severity=S.MEDIUM,
        confidence=C.LOW,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "Contract request schema and implementation body-model names disagree, or only "
            "one side declares a request body. LOW confidence: names need not coincide."
        ),
    ),
    DriftCheckSpec(
        id="DRIFT006",
        title="Response schema mismatch",
        severity=S.MEDIUM,
        confidence=C.LOW,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "Contract response schema and implementation response model names disagree, or "
            "only one side declares a response schema. LOW confidence."
        ),
    ),
    DriftCheckSpec(
        id="DRIFT007",
        title="Status-code drift",
        severity=S.LOW,
        confidence=C.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "The implementation's declared status codes do not intersect the contract's "
            "success (2xx) responses, or the implementation raises error statuses the "
            "contract does not declare."
        ),
    ),
    DriftCheckSpec(
        id="DRIFT008",
        title="Auth drift",
        severity=S.MEDIUM,
        confidence=C.LOW,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "Contract requires named security while the route shows no `Security` "
            "dependency evidence, or the route carries security evidence while the contract "
            "requires none. LOW confidence: auth may be enforced by middleware/gateway."
        ),
    ),
    DriftCheckSpec(
        id="DRIFT009",
        title="Deprecated contract still implemented",
        severity=S.LOW,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger="A `deprecated: true` contract operation still has a live route.",
    ),
    DriftCheckSpec(
        id="DRIFT010",
        title="Undocumented breaking implementation",
        severity=S.MEDIUM,
        confidence=C.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "An unmatched route uses a write method (POST/PUT/PATCH/DELETE): the "
            "implementation exposes surface the contract does not describe — potentially "
            "breaking for contract-first consumers."
        ),
    ),
)

BY_ID: dict[str, DriftCheckSpec] = {spec.id: spec for spec in CATALOG}
