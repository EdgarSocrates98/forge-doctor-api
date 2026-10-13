"""Core models -> ``forge-contracts/1`` wire payloads (spec 074).

The shared vocabulary is the contract: findings, entities,
relationships, capabilities, unknowns, plans, bundles, manifests.
API-doctor specifics (entity_ids, evidence refs, protocol/operation
identity, compatibility class, runtime signals) travel under the
``x-forge-api`` extension namespace — never reshaped into core fields.

No ``forge_doctor_data`` import exists anywhere in this package: the
doctors share the published contract, not each other's internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from forge_doctor_api.contracts.models import (
    API_EXTENSION,
    Capability,
    DiagnosticManifest,
    Entity,
    Evidence,
    Finding,
    HandoffBundle,
    Relationship,
    UnknownFact,
)
from forge_doctor_api.core.models import ModelError, parse_entity_id

if TYPE_CHECKING:
    from forge_doctor_api.core.graph import EdgeExport
    from forge_doctor_api.core.models import (
        Entity as CoreEntity,
    )
    from forge_doctor_api.core.models import (
        Evidence as CoreEvidence,
    )
    from forge_doctor_api.core.models import (
        Finding as CoreFinding,
    )
    from forge_doctor_api.core.models import (
        Relationship as CoreRelationship,
    )
    from forge_doctor_api.core.models import (
        Severity,
    )
    from forge_doctor_api.core.models import (
        UnknownFact as CoreUnknownFact,
    )
    from forge_doctor_api.knowledge.capability import (
        CapabilityGap,
        DetectedCapability,
    )
    from forge_doctor_api.report import DoctorReport

TOOL_NAME = "forge-doctor-api"

_SEVERITY_MAP: dict[str, str] = {
    "CRITICAL": "error",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "info",
    "INFO": "info",
}

_CONFIDENCE_STATUS: dict[str, str] = {
    "HIGH": "supported",
    "MEDIUM": "partial",
    "LOW": "partial",
    "UNKNOWN": "unknown",
}


def wire_severity(severity: Severity) -> str:
    """Core severity -> wire enum (error|warning|info|pass)."""
    return _SEVERITY_MAP[severity.value]


def wire_evidence(ev: CoreEvidence) -> Evidence:
    ref = ev.source
    if ev.line is not None:
        ref = f"{ref}:L{ev.line}"
    return Evidence(
        ref=ref,
        kind=ev.kind.value.lower(),
        source=TOOL_NAME,
        detail=ev.summary,
    )


def _evidence_refs(evidence: tuple[CoreEvidence, ...]) -> tuple[str, ...]:
    return tuple(wire_evidence(e).ref for e in evidence)


def wire_finding(f: CoreFinding) -> Finding:
    """Core Finding -> wire ``finding``; API fields under x-forge-api."""
    evidence = _evidence_refs(f.evidence)
    extensions: dict[str, Any] = {}
    domain_fields: dict[str, Any] = {}
    if f.entity_ids:
        domain_fields["entity_ids"] = list(f.entity_ids)
    if f.evidence:
        domain_fields["evidence_refs"] = list(evidence)
    if f.unknowns:
        domain_fields["unknowns"] = [
            {"subject": u.subject, "missing": u.missing,
             "resolution": u.resolution}
            for u in f.unknowns
        ]
    if domain_fields:
        extensions[API_EXTENSION] = domain_fields
    return Finding(
        extensions=extensions,
        check_id=f.id,
        title=f.title,
        severity=wire_severity(f.severity),
        category=f.namespace.lower(),
        message=f.description,
        file=f.source_location.path if f.source_location else None,
        line=f.source_location.line if f.source_location else None,
        column=f.source_location.column if f.source_location else None,
        recommendation=f.remediation,
        confidence=f.confidence.value.lower(),
        evidence=evidence[0] if evidence else None,
        evidence_kind=f.evidence_kind.value.lower(),
        source=TOOL_NAME,
    )


def wire_entity(e: CoreEntity) -> Entity:
    """Core Entity -> wire ``entity``; canonical id decomposes to parts."""
    kind, domain, identifier = parse_entity_id(e.id)
    file = e.attributes.get("file")
    line_raw = e.attributes.get("line")
    line = int(line_raw) if line_raw and str(line_raw).isdigit() else None
    return Entity(
        id=e.id,
        kind=kind,
        domain=domain,
        identifier=identifier,
        name=e.name,
        file=file,
        line=line,
        attrs=dict(e.attributes),
    )


def wire_relationship(r: CoreRelationship) -> Relationship:
    """Core Relationship -> wire ``relationship`` edge."""
    first = r.evidence[0] if r.evidence else None
    extensions: dict[str, Any] = {}
    if r.unknowns:
        extensions[API_EXTENSION] = {
            "unknowns": [
                {"subject": u.subject, "missing": u.missing,
                 "resolution": u.resolution}
                for u in r.unknowns
            ]
        }
    return Relationship(
        extensions=extensions,
        src=r.source_id,
        dst=r.target_id,
        kind=r.kind,
        evidence_kind=first.kind.value.lower() if first else None,
        attrs={"confidence": r.confidence.value.lower()},
    )


def wire_unknown(u: CoreUnknownFact) -> UnknownFact:
    """Core UnknownFact -> wire honest-UNKNOWN shape."""
    return UnknownFact(
        subject=u.subject,
        kind="evidence",
        reason=u.missing,
        source=TOOL_NAME,
        detail=u.resolution,
    )


def wire_capability(c: DetectedCapability) -> Capability:
    """Detected capability -> wire ``capability`` (evidence refs only)."""
    return Capability(
        id=c.capability.value,
        domain="api",
        status="supported",
        evidence_refs=_evidence_refs(c.evidence),
    )


def wire_capability_gap(gap: CapabilityGap) -> Capability:
    """A dependency gap is a *partial* capability — never silently absent."""
    return Capability(
        id=gap.capability.value,
        domain="api",
        status="partial",
        confidence="high",
        evidence_refs=(),
    )


def wire_edge_export(edge: EdgeExport) -> Relationship:
    """Report-level EdgeExport -> wire ``relationship``."""
    return Relationship(
        extensions={API_EXTENSION: {
            "evidence_ids": list(edge.evidence_ids)}},
        src=edge.from_id,
        dst=edge.to_id,
        kind=edge.kind,
        attrs={"confidence": edge.confidence.value.lower()},
    )


def entity_from_id(raw: str) -> Entity | UnknownFact:
    """Decompose a canonical entity id into a wire ``entity``.

    Non-canonical ids become an honest UnknownFact — the wire never
    fabricates kind/domain splits it cannot prove.
    """
    try:
        kind, domain, identifier = parse_entity_id(raw)
    except ModelError:
        return UnknownFact(
            subject=raw,
            kind="entity",
            reason="non-canonical entity id — cannot decompose",
            source=TOOL_NAME,
        )
    return Entity(
        id=raw, kind=kind, domain=domain,
        identifier=identifier, name=identifier,
    )


def report_handoff(
    report: DoctorReport,
    *,
    tool_version: str = "",
    project: dict[str, Any] | None = None,
) -> HandoffBundle:
    """``DoctorReport`` -> conforming ``handoff`` bundle.

    Every findings/unknown/capability the report carries is translated;
    graph edges become wire relationships; entity ids referenced by the
    domain projections become wire entities. Sorted before emission —
    the wire order is the canonical order.
    """
    findings = tuple(sorted(
        (wire_finding(f) for f in report.findings),
        key=lambda w: (w.check_id, w.file or "", w.line or 0),
    ))
    entities: list[Entity] = []
    entity_unknowns: list[UnknownFact] = []
    seen: set[str] = set()
    for projection in (
        report.contracts, report.routes, report.clients, report.graph,
        report.gateway, report.mesh, report.infrastructure, report.cache,
        report.runtime, report.security, report.reliability,
        report.policies, report.twin, report.fanout, report.migration,
        report.impact,
    ):
        if projection is None:
            continue
        for raw in projection.ids:
            if raw in seen:
                continue
            seen.add(raw)
            node = entity_from_id(raw)
            if isinstance(node, Entity):
                entities.append(node)
            else:
                entity_unknowns.append(node)
    relationships = tuple(sorted(
        (wire_edge_export(e) for e in report.graph_edges),
        key=lambda w: (w.src, w.kind, w.dst),
    ))
    capabilities = tuple(sorted(
        (wire_capability(c) for c in report.capabilities),
        key=lambda w: w.id,
    ))
    unknowns = tuple(sorted(
        (*(wire_unknown(u) for u in report.unknowns), *entity_unknowns),
        key=lambda w: (w.subject, w.reason),
    ))
    summary = {
        "findings": len(findings),
        "entities": len(entities),
        "relationships": len(relationships),
        "capabilities": len(capabilities),
        "unknowns": len(unknowns),
        "verdict": "pass" if not findings else "pass-with-findings",
    }
    return HandoffBundle(
        tool=TOOL_NAME,
        tool_version=tool_version or report.tool_version,
        project=project or {"name": report.project or ""},
        summary=summary,
        findings=findings,
        entities=tuple(sorted(entities, key=lambda e: e.id)),
        relationships=relationships,
        capabilities=capabilities,
        unknowns=unknowns,
        extensions={API_EXTENSION: {
            "analysis_rev": report.analysis_rev,
            "schema_version": report.schema_version,
        }},
    )


def report_manifest(
    report: DoctorReport,
    *,
    tool_version: str = "",
) -> DiagnosticManifest:
    """``DoctorReport`` -> conforming ``diagnostic-manifest``."""
    bundle = report_handoff(report, tool_version=tool_version)
    domains = sorted({
        e.domain for e in bundle.entities
    } | {f.category for f in bundle.findings} - {""})
    return DiagnosticManifest(
        tool=TOOL_NAME,
        tool_version=tool_version or report.tool_version,
        domains=tuple(domains),
        entity_count=len(bundle.entities),
        finding_count=len(bundle.findings),
        unknown_count=len(bundle.unknowns),
        capabilities=bundle.capabilities,
        evidence_refs=tuple(sorted({
            ref
            for f in bundle.findings
            for ref in (f.extensions.get(API_EXTENSION, {})
                        .get("evidence_refs", ()))
        })),
        extensions={API_EXTENSION: {
            "analysis_rev": report.analysis_rev}},
    )
