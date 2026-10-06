"""COMPAT### check catalog (§16, §218).

Every change class maps §16.2 breaking rules and §16.3 non-breaking
candidates onto stable ids. `POTENTIALLY_BREAKING` means "safe only under
client semantics the contract cannot prove" (§16.3) — never a guarantee.
`UNKNOWN` means the evidence itself was insufficient (§16.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Confidence, EvidenceKind, Severity


class CompatibilityClass(StrEnum):
    """§16.1 change classes."""

    NON_BREAKING = "NON_BREAKING"
    POTENTIALLY_BREAKING = "POTENTIALLY_BREAKING"
    BREAKING = "BREAKING"
    UNKNOWN = "UNKNOWN"


class ChangeSide(StrEnum):
    """Request and response compatibility are separate semantics (§123)."""

    REQUEST = "request"
    RESPONSE = "response"
    META = "meta"


@dataclass(frozen=True)
class CompatCheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    change_kind: str
    trigger: str


CATALOG: tuple[CompatCheckSpec, ...] = (
    CompatCheckSpec("COMPAT001", "Endpoint removed", Severity.HIGH, Confidence.HIGH,
                    EvidenceKind.STATIC, "endpoint_removed",
                    "A path present in the old contract is absent from the new one."),
    CompatCheckSpec("COMPAT002", "Method removed", Severity.HIGH, Confidence.HIGH,
                    EvidenceKind.STATIC, "method_removed",
                    "A method on an existing path was removed."),
    CompatCheckSpec("COMPAT003", "Required parameter added", Severity.HIGH, Confidence.HIGH,
                    EvidenceKind.STATIC, "param_added_required",
                    "A new required parameter appeared on an existing operation."),
    CompatCheckSpec("COMPAT004", "Parameter removed", Severity.HIGH, Confidence.HIGH,
                    EvidenceKind.STATIC, "param_removed",
                    "A documented parameter no longer exists on the operation."),
    CompatCheckSpec("COMPAT005", "Parameter/request field type changed",
                    Severity.HIGH, Confidence.HIGH, EvidenceKind.STATIC,
                    "type_changed_request",
                    "A request-side parameter or field changed type incompatibly."),
    CompatCheckSpec("COMPAT006", "Request field became required", Severity.HIGH,
                    Confidence.HIGH, EvidenceKind.STATIC, "request_field_required",
                    "An optional or absent request field is now required."),
    CompatCheckSpec("COMPAT007", "Response field removed", Severity.HIGH, Confidence.HIGH,
                    EvidenceKind.STATIC, "response_field_removed",
                    "A field present in the old response schema is gone."),
    CompatCheckSpec("COMPAT008", "Response type narrowed or changed", Severity.HIGH,
                    Confidence.HIGH, EvidenceKind.STATIC, "type_changed_response",
                    "A response field/type narrowed or changed incompatibly."),
    CompatCheckSpec("COMPAT009", "Enum value removed", Severity.HIGH, Confidence.HIGH,
                    EvidenceKind.STATIC, "enum_removed",
                    "An enum value the contract used to allow was removed."),
    CompatCheckSpec("COMPAT010", "Status code removed", Severity.MEDIUM, Confidence.HIGH,
                    EvidenceKind.STATIC, "status_removed",
                    "A documented response status disappeared."),
    CompatCheckSpec("COMPAT011", "Auth requirement tightened", Severity.HIGH, Confidence.HIGH,
                    EvidenceKind.STATIC, "auth_tightened",
                    "The operation now requires security where it did not, or requires "
                    "additional schemes."),
    CompatCheckSpec("COMPAT012", "Content-type removed", Severity.MEDIUM, Confidence.HIGH,
                    EvidenceKind.STATIC, "content_type_removed",
                    "A documented media type is no longer produced or consumed."),
    CompatCheckSpec("COMPAT020", "Response field added (candidate)", Severity.LOW,
                    Confidence.MEDIUM, EvidenceKind.STATIC, "response_field_added",
                    "A new field appears in a response schema. POTENTIALLY_BREAKING: "
                    "strictly-decoding clients may reject it."),
    CompatCheckSpec("COMPAT021", "Endpoint added (candidate)", Severity.INFO,
                    Confidence.HIGH, EvidenceKind.STATIC, "endpoint_added",
                    "A new path or method appeared. POTENTIALLY_BREAKING under unknown "
                    "client semantics per §16.3."),
    CompatCheckSpec("COMPAT022", "Optional parameter added (candidate)", Severity.LOW,
                    Confidence.HIGH, EvidenceKind.STATIC, "param_added_optional",
                    "A new optional parameter appeared on an existing operation."),
    CompatCheckSpec("COMPAT023", "Enum value added (candidate)", Severity.LOW,
                    Confidence.MEDIUM, EvidenceKind.STATIC, "enum_added",
                    "An enum gained a value. POTENTIALLY_BREAKING: clients matching "
                    "exhaustively may not handle it."),
    CompatCheckSpec("COMPAT024", "Auth requirement loosened", Severity.LOW,
                    Confidence.HIGH, EvidenceKind.STATIC, "auth_loosened",
                    "Required security schemes were dropped. NON_BREAKING for clients, "
                    "flagged so security review sees it."),
    CompatCheckSpec("COMPAT025", "Request body added", Severity.MEDIUM, Confidence.HIGH,
                    EvidenceKind.STATIC, "request_body_added",
                    "An operation gained a request body. POTENTIALLY_BREAKING: old "
                    "clients never send one."),
    CompatCheckSpec("COMPAT026", "Request field added (optional)", Severity.LOW,
                    Confidence.HIGH, EvidenceKind.STATIC, "request_field_added",
                    "An optional field appeared in a request schema."),
    CompatCheckSpec("COMPAT027", "Request field removed", Severity.MEDIUM,
                    Confidence.HIGH, EvidenceKind.STATIC, "request_field_removed",
                    "A field was removed from a request schema. POTENTIALLY_BREAKING: "
                    "servers may now reject clients still sending it."),
    CompatCheckSpec("COMPAT028", "Response type widened", Severity.MEDIUM,
                    Confidence.MEDIUM, EvidenceKind.STATIC, "response_type_widened",
                    "A response type widened. POTENTIALLY_BREAKING: strictly-typed "
                    "clients may not handle the new range."),
    CompatCheckSpec("COMPAT030", "Change detail unresolvable", Severity.MEDIUM,
                    Confidence.LOW, EvidenceKind.STATIC, "unresolvable",
                    "A schema/structure changed but static evidence cannot decompose it "
                    "(unresolved refs, dynamic composition). Classified UNKNOWN."),
)

BY_ID: dict[str, CompatCheckSpec] = {spec.id: spec for spec in CATALOG}
CHANGE_TO_SPEC: dict[str, CompatCheckSpec] = {spec.change_kind: spec for spec in CATALOG}
