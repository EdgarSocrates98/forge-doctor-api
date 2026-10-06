"""Unified DoctorReport — canonical compact report (§16).

One frozen model carrying every domain the deterministic pipeline can
observe. Domains are *compact projections* (`DomainSummary`) — counts,
entity ids and headline summaries — never payloads: no schema bodies,
no raw spans, no source text, no configs.

A domain is `None` when the analysis plan found no evidence for it;
absence is data, never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_doctor_api.checks.compat.engine import ContractDiff
from forge_doctor_api.core.discovery import ArtifactInventory
from forge_doctor_api.core.gate import GateFailure
from forge_doctor_api.core.graph import EdgeExport
from forge_doctor_api.core.models import Finding, Model, UnknownFact
from forge_doctor_api.core.plan import AnalysisPlan
from forge_doctor_api.core.report import DomainSummary
from forge_doctor_api.knowledge.capability import DetectedCapability

DOCTOR_REPORT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, kw_only=True)
class DoctorReport(Model):
    """The unified report every surface (CLI/SDK/MCP/handoff) consumes."""

    schema_version: str = DOCTOR_REPORT_SCHEMA_VERSION
    tool_version: str = ""
    knowledge_versions: tuple[tuple[str, str], ...] = ()
    project: str | None = None

    # pipeline metadata
    inventory: ArtifactInventory | None = None
    plan: AnalysisPlan | None = None
    analysis_rev: str | None = None  # content hash of this report's inputs
    analysis_stats: tuple[tuple[str, str], ...] = ()  # legacy slot
    stats: Any = None  # spec 066 AnalysisStats (duration_ms only under flag)

    # domain projections — None when the domain had no evidence
    contracts: DomainSummary | None = None
    routes: DomainSummary | None = None
    clients: DomainSummary | None = None
    graph: DomainSummary | None = None
    graph_edges: tuple[EdgeExport, ...] = ()
    gateway: DomainSummary | None = None
    mesh: DomainSummary | None = None
    infrastructure: DomainSummary | None = None
    cache: DomainSummary | None = None
    runtime: DomainSummary | None = None
    security: DomainSummary | None = None
    reliability: DomainSummary | None = None
    policies: DomainSummary | None = None
    twin: DomainSummary | None = None
    fanout: DomainSummary | None = None
    migration: DomainSummary | None = None

    # result surfaces
    capabilities: tuple[DetectedCapability, ...] = ()
    findings: tuple[Finding, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()
    operations: tuple[str, ...] = ()
    changes: tuple[str, ...] = ()
    impact: DomainSummary | None = None
    remediation_candidates: tuple[str, ...] = ()

    # compatibility with the pre-unification ScanReport
    diff: ContractDiff | None = None
    gate_failures: tuple[GateFailure, ...] = ()

    @property
    def gate_passed(self) -> bool:
        return not self.gate_failures

    def artifact_counts(self) -> dict[str, int]:
        if self.inventory is None:
            return {}
        return self.inventory.counts_by_class()
