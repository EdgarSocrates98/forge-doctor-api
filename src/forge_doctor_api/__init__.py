"""Forge Doctor API: deterministic API architecture intelligence.

Public surface (stable): `Doctor` facade, `DoctorReport`, core models
and the handoff bundle. Everything else is internal and may move —
import from here, not from deep module paths.
"""

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.discovery import ArtifactInventory
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Model,
    Severity,
    SourceLocation,
    UnknownFact,
)
from forge_doctor_api.core.plan import AnalysisPlan
from forge_doctor_api.core.report import DomainSummary
from forge_doctor_api.handoff.bundle import assemble_bundle
from forge_doctor_api.handoff.model import ApiHandoffBundle
from forge_doctor_api.handoff.protocol import (
    ForgeHandoff,
    ForgeReceipt,
    ForgeRef,
    ForgeRequest,
    ForgeResult,
)
from forge_doctor_api.report import DoctorReport
from forge_doctor_api.sdk import (
    SDK_VERSION,
    Doctor,
    DoctorError,
    FindingNotFoundError,
    ProjectUnreadableError,
)

__version__ = "0.2.0"

__all__ = [
    "SDK_VERSION",
    "AnalysisPlan",
    "ApiHandoffBundle",
    "ArtifactInventory",
    "Confidence",
    "Doctor",
    "DoctorError",
    "DoctorReport",
    "DomainSummary",
    "Evidence",
    "EvidenceKind",
    "Finding",
    "FindingNotFoundError",
    "ForgeHandoff",
    "ForgeReceipt",
    "ForgeRef",
    "ForgeRequest",
    "ForgeResult",
    "Model",
    "ProjectContext",
    "ProjectUnreadableError",
    "Severity",
    "SourceLocation",
    "UnknownFact",
    "__version__",
    "assemble_bundle",
]
