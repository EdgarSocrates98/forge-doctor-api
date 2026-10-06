"""forge-contracts/1 — the shared cross-doctor wire contract.

The API Doctor and Data Doctor speak the same wire vocabulary so The
Forger can consume either through one ``DoctorEndpoint`` shape. This
package vendors the canonical contract (models, schemas, version
negotiation) and adapts core models onto it — no ``forge_doctor_data``
import; domain internals stay independent (spec 074).
"""

from forge_doctor_api.contracts.adapters import (
    entity_from_id,
    report_handoff,
    report_manifest,
    wire_capability,
    wire_capability_gap,
    wire_edge_export,
    wire_entity,
    wire_evidence,
    wire_finding,
    wire_relationship,
    wire_severity,
    wire_unknown,
)
from forge_doctor_api.contracts.models import (
    API_EXTENSION,
    CONTRACT_VERSION,
    Capability,
    ContractModel,
    DiagnosticManifest,
    Entity,
    Evidence,
    Finding,
    HandoffBundle,
    MigrationPlan,
    Relationship,
    RemediationPlan,
    UnknownFact,
)
from forge_doctor_api.contracts.schemas import FORGE_CONTRACT_SCHEMAS
from forge_doctor_api.contracts.validate import (
    ContractError,
    assert_valid,
    validate,
    validate_named,
)
from forge_doctor_api.contracts.version import (
    CURRENT,
    SUPPORTED,
    ContractVersion,
    negotiate,
    within_range,
)

__all__ = [
    "API_EXTENSION",
    "CONTRACT_VERSION",
    "CURRENT",
    "FORGE_CONTRACT_SCHEMAS",
    "SUPPORTED",
    "Capability",
    "ContractError",
    "ContractModel",
    "ContractVersion",
    "DiagnosticManifest",
    "Entity",
    "Evidence",
    "Finding",
    "HandoffBundle",
    "MigrationPlan",
    "Relationship",
    "RemediationPlan",
    "UnknownFact",
    "assert_valid",
    "entity_from_id",
    "negotiate",
    "report_handoff",
    "report_manifest",
    "validate",
    "validate_named",
    "wire_capability",
    "wire_capability_gap",
    "wire_edge_export",
    "wire_entity",
    "wire_evidence",
    "wire_finding",
    "wire_relationship",
    "wire_severity",
    "wire_unknown",
    "within_range",
]
