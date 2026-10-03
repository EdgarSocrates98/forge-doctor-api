"""§177-§178 project scan + CI gate evaluation.

`scan_project` runs the deterministic pipelines over a context and returns
findings plus the contract diff when a baseline is provided.
`evaluate_gate` applies the §178 fail-on categories; findings at
Confidence.UNKNOWN never block a gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from forge_doctor_api.analyzers.asyncapi.parser import load_asyncapi_project
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.graphql.parser import load_graphql_project
from forge_doctor_api.analyzers.grpc.parser import load_grpc_project
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.runtime.execution import (
    executions_from_traces,
)
from forge_doctor_api.analyzers.runtime.loader import load_runtime_project
from forge_doctor_api.analyzers.version.detect import detect_version_model
from forge_doctor_api.checks.apisec.engine import run_security_checks
from forge_doctor_api.checks.asyncapi.engine import run_async_checks
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractDiff, diff_models
from forge_doctor_api.checks.graphql.engine import run_graphql_checks
from forge_doctor_api.checks.grpc.engine import run_grpc_checks
from forge_doctor_api.checks.oas.engine import run_openapi_checks
from forge_doctor_api.checks.observability.engine import (
    run_observability_checks,
)
from forge_doctor_api.checks.perf.engine import run_perf_checks
from forge_doctor_api.checks.relapi.engine import run_reliability_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Confidence,
    Finding,
    Model,
    UnknownFact,
    check_namespace,
)
from forge_doctor_api.knowledge import knowledge_versions
from forge_doctor_api.policy.engine import evaluate_policies
from forge_doctor_api.policy.loader import load_policies
from forge_doctor_api.policy.ownership import resolve_ownership
from forge_doctor_api.policy.rules import RuleContext
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.security import load_security_model


class GateCategory(StrEnum):
    """§178 configurable gate categories."""

    BREAKING = "breaking"
    SECURITY = "security"
    POLICY = "policy"


@dataclass(frozen=True, kw_only=True)
class GateFailure(Model):
    """One §178 gate trigger: category + evidence-bearing subjects."""

    category: GateCategory
    subjects: tuple[str, ...]
    detail: str


@dataclass(frozen=True, kw_only=True)
class ScanReport(Model):
    """scan result: findings + diff + gate evaluation."""

    findings: tuple[Finding, ...] = ()
    diff: ContractDiff | None = None
    gate_failures: tuple[GateFailure, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    @property
    def gate_passed(self) -> bool:
        return not self.gate_failures


def _findings_of(namespace: str, findings: tuple[Finding, ...],
                 min_confidence: Confidence) -> tuple[str, ...]:
    return tuple(
        f"{f.id}: {f.description}"
        for f in findings
        if check_namespace(f.id) == namespace
        and f.confidence is not Confidence.UNKNOWN
        and _CONF_RANK[f.confidence] >= _CONF_RANK[min_confidence]
    )


_CONF_RANK = {
    Confidence.UNKNOWN: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}


def evaluate_gate(
    findings: tuple[Finding, ...],
    diff: ContractDiff | None,
    fail_on: frozenset[GateCategory],
) -> tuple[GateFailure, ...]:
    """§178 — UNKNOWN-confidence findings never produce a failure."""
    failures: list[GateFailure] = []
    if GateCategory.BREAKING in fail_on:
        if diff is None:
            raise _GateConfigError(
                "fail-on=breaking requires a --baseline contract context")
        breaking = tuple(
            f"{c.kind}: {c.subject} {c.path}".strip()
            for c in diff.changes
            if c.classification is CompatibilityClass.BREAKING
        )
        if breaking:
            failures.append(GateFailure(
                category=GateCategory.BREAKING,
                subjects=breaking,
                detail=f"{len(breaking)} breaking change(s) detected",
            ))
    if GateCategory.SECURITY in fail_on:
        hits = _findings_of("APISEC", findings, Confidence.HIGH)
        if hits:
            failures.append(GateFailure(
                category=GateCategory.SECURITY,
                subjects=hits,
                detail=f"{len(hits)} high-confidence security issue(s)",
            ))
    if GateCategory.POLICY in fail_on:
        hits = _findings_of("POLICY", findings, Confidence.LOW)
        if hits:
            failures.append(GateFailure(
                category=GateCategory.POLICY,
                subjects=hits,
                detail=f"{len(hits)} policy violation(s)",
            ))
    return tuple(failures)


class _GateConfigError(ValueError):
    """fail-on category requested without the inputs it needs."""


def scan_project(
    context: ProjectContext,
    *,
    before: ProjectContext | None = None,
    extra_policy: ProjectContext | None = None,
    today: date | None = None,
) -> ScanReport:
    """Run every deterministic pipeline; attach the diff when given."""
    files = list(context.iter_files())
    findings: list[Finding] = []

    openapi = load_openapi_project(context)
    findings.extend(run_openapi_checks(openapi))

    security = load_security_model(context, files, openapi=openapi)
    findings.extend(run_security_checks(security, openapi))

    reliability = load_reliability_model(context, files)
    findings.extend(run_reliability_checks(reliability))

    clients = scan_clients(context, files)

    graphql = load_graphql_project(context, files)
    if graphql.documents:
        findings.extend(run_graphql_checks(graphql))
    grpc = load_grpc_project(context, files)
    if grpc.files:
        findings.extend(run_grpc_checks(grpc))
    asyncapi = load_asyncapi_project(context)
    if asyncapi.documents:
        findings.extend(run_async_checks(asyncapi))

    traces, observability, rt_unknowns = load_runtime_project(
        context, files, keep_spans=True)
    findings.extend(run_observability_checks(observability))
    executions, exec_unknowns = executions_from_traces(traces)
    findings.extend(run_perf_checks(executions))

    policy_set = load_policies(context, files)
    if extra_policy is not None:
        extra = load_policies(extra_policy, list(extra_policy.iter_files()))
        from forge_doctor_api.policy.model import PolicySet
        policy_set = PolicySet(
            policies=policy_set.policies + extra.policies,
            exceptions=policy_set.exceptions + extra.exceptions,
            issues=policy_set.issues + extra.issues,
            unknowns=policy_set.unknowns + extra.unknowns,
        )
    if policy_set.policies or policy_set.exceptions or policy_set.issues:
        version = detect_version_model(openapi)
        ownership = resolve_ownership(context, files, openapi)
        findings.extend(evaluate_policies(
            policy_set,
            RuleContext(openapi=openapi, security=security,
                        reliability=reliability, version=version,
                        ownership=ownership),
            today or date.min,
        ))

    diff: ContractDiff | None = None
    if before is not None:
        diff = diff_models(load_openapi_project(before), openapi)
        findings.extend(diff.findings)

    return ScanReport(
        findings=tuple(sorted(
            findings,
            key=lambda f: (f.id, f.entity_ids, f.description))),
        diff=diff,
        unknowns=tuple(
            [*rt_unknowns, *exec_unknowns, *clients.unknowns]
            + [
                UnknownFact(
                    subject=r.ref,
                    missing="external reference content",
                    resolution="provide the referenced document locally",
                )
                for r in openapi.unresolved_external_refs
            ]),
    )


def export_scan(report: ScanReport) -> dict[str, object]:
    """§174 metadata-carrying scan export."""
    from forge_doctor_api import __version__
    return {
        "schema_version": "1.0",
        "tool_version": __version__,
        "knowledge_versions": knowledge_versions(),
        "gate_passed": report.gate_passed,
        "gate_failures": [f.to_dict() for f in report.gate_failures],
    }
