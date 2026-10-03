"""§134 bundle assembly — compact references + summaries (§135)."""

from __future__ import annotations

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiProjectModel,
    OperationSource,
)
from forge_doctor_api.checks.client.engine import ImpactReport
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractDiff
from forge_doctor_api.core.models import Finding, UnknownFact, check_namespace
from forge_doctor_api.handoff.model import ApiHandoffBundle, ExternalReference
from forge_doctor_api.knowledge import knowledge_versions
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

    return ApiHandoffBundle(
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
