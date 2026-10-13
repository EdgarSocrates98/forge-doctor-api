"""§134 bundle assembly — compact references + summaries (§135)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiProjectModel,
    OperationSource,
)
from forge_doctor_api.checks.client.engine import ImpactReport
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractDiff
from forge_doctor_api.core.models import Finding, UnknownFact, check_namespace
from forge_doctor_api.handoff.context import (
    content_digest,
    finding_refs,
    mint,
)
from forge_doctor_api.handoff.model import ApiHandoffBundle, ExternalReference
from forge_doctor_api.handoff.protocol import (
    ForgeCapability,
    ForgeHandoff,
    ForgeRef,
    build_receipt,
)
from forge_doctor_api.knowledge import knowledge_versions
from forge_doctor_api.report import DoctorReport
from forge_doctor_api.safefix.classify import classify_findings


def _summarize(f: Finding) -> str:
    subject = f.entity_ids[0] if f.entity_ids else (
        f.source_location.path if f.source_location else "")
    return f"{f.id} {subject}: {f.title}".strip()


def assemble_bundle(
    *,
    service: str | None = None,
    openapi: OpenApiProjectModel | None = None,
    findings: tuple[Finding, ...] = (),
    diff: ContractDiff | None = None,
    impact: ImpactReport | None = None,
    external_references: tuple[ExternalReference, ...] = (),
    unknowns: tuple[UnknownFact, ...] = (),
    handoff_version: Literal[1, 2] = 1,
    report: DoctorReport | None = None,
) -> ApiHandoffBundle:
    """Assemble a compact handoff bundle from computed outputs.

    Every field is a reference or summary — no contract payloads, no source
    bodies. Callers pass already-computed models; nothing is re-scanned.
    """
    operations: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()
    if openapi is not None:
        operations = tuple(
            f"{o.method.upper()} {o.path}"
            for o in openapi.operations
            if o.source is OperationSource.PATH
        )
        contracts = tuple(
            f"{d.location.path} openapi={d.openapi_version}"
            if d.openapi_version else d.location.path
            for d in openapi.documents
        )
        service = service or next(
            (d.title for d in openapi.documents if d.title), None,
        )

    breaking: tuple[str, ...] = ()
    if diff is not None:
        breaking = tuple(
            f"{c.kind}: {c.subject} {c.path}".strip()
            for c in diff.changes
            if c.classification is CompatibilityClass.BREAKING
        )

    clients: tuple[str, ...] = ()
    if impact is not None:
        clients = tuple(sorted({
            c for entry in impact.entries for c in entry.clients
        }))

    def fam(ns: str) -> tuple[str, ...]:
        return tuple(_summarize(f) for f in findings
                     if check_namespace(f.id) == ns)

    bundle = ApiHandoffBundle(
        service=service,
        operations=operations,
        contracts=contracts,
        findings=findings,
        breaking_changes=breaking,
        clients_affected=clients,
        runtime_regressions=fam("APIPERF") + fam("OBSAPI"),
        security_candidates=fam("APISEC"),
        reliability_signals=fam("RELAPI"),
        external_references=external_references,
        remediation_candidates=classify_findings(findings).candidates,
        unknowns=unknowns + tuple(
            u for f in findings for u in f.unknowns
        ),
        knowledge_versions=knowledge_versions(),
    )
    if handoff_version == 2:
        if report is None:
            raise ValueError(
                "handoff_version=2 requires the source DoctorReport")
        bundle = upgrade_bundle(bundle, report)
    return bundle


_DOMAIN_FIELDS = (
    "contracts", "routes", "clients", "graph", "gateway", "mesh",
    "infrastructure", "cache", "runtime", "security", "reliability",
    "policies", "twin", "fanout", "migration", "impact",
)


def _bundle_sha256(bundle: ApiHandoffBundle) -> str:
    """Content hash of the V1 body (V2 fields excluded by construction)."""
    return bundle.body_sha256()


def upgrade_bundle(
    bundle: ApiHandoffBundle,
    report: DoctorReport,
) -> ApiHandoffBundle:
    """§134 V2: deterministic identity + content addressing + refs."""
    domain_hashes: list[tuple[str, str]] = []
    for name in _DOMAIN_FIELDS:
        summary = getattr(report, name, None)
        if summary is not None:
            domain_hashes.append(
                (name, content_digest(summary.to_json())))
    caps = tuple(
        ForgeCapability(name=c.capability.value, status="detected")
        for c in report.capabilities
    )
    refs = (
        mint("service"),
        mint("graph"),
        mint("runtime"),
        mint("contract"),
        mint("capability"),
        *(mint("unknown", i=i) for i in range(len(report.unknowns))),
        *finding_refs(report),
    )
    v1 = replace(bundle, handoff_version=2)
    return replace(
        v1,
        handoff_id=_bundle_sha256(v1),
        analysis_rev=report.analysis_rev,
        domain_sha256=tuple(sorted(domain_hashes)),
        context_refs=refs,
        capabilities=caps,
        graph_edges=report.graph_edges,
    )


def assemble_bundle_v2(
    report: DoctorReport,
    **kwargs: Any,
) -> ApiHandoffBundle:
    """assemble_bundle -> upgrade to V2 in one step."""
    return upgrade_bundle(assemble_bundle(**kwargs), report)


def build_handoff(
    report: DoctorReport,
    bundle: ApiHandoffBundle,
) -> ForgeHandoff:
    """§26 typed handoff envelope over a V2 bundle."""
    refs = tuple(
        ForgeRef(ref_id=r, kind=r.split("/")[2], sha256=bundle.handoff_id)
        for r in bundle.context_refs
    )
    unknown_refs = tuple(
        ForgeRef(ref_id=mint("unknown", i=i), kind="unknown",
                 entity=u.subject, summary=u.missing)
        for i, u in enumerate(report.unknowns)
    )
    return ForgeHandoff(
        handoff_id=bundle.handoff_id,
        bundle_ref=mint("handoff", id=bundle.handoff_id),
        analysis_rev=report.analysis_rev,
        refs=refs,
        capabilities=bundle.capabilities,
        unknowns=unknown_refs,
    )


__all__ = [
    "assemble_bundle",
    "assemble_bundle_v2",
    "build_handoff",
    "build_receipt",
    "upgrade_bundle",
]
