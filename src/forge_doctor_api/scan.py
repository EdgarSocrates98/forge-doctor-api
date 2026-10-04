"""§177-§178 unified project scan + CI gate evaluation.

Pipeline (§15): ProjectContext -> Artifact Discovery -> Evidence
Inventory -> AnalysisPlan -> applicable analyzers -> normalized models
-> service graph -> digital twin -> correlation -> checks -> findings /
capabilities / unknowns / impact -> DoctorReport.

`scan_project` runs every analyzer the evidence-driven `AnalysisPlan`
enables; nothing runs without artifact evidence, nothing fabricates a
domain that had none. `evaluate_gate` applies the §178 fail-on
categories; findings at Confidence.UNKNOWN never block a gate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from forge_doctor_api.analyzers.asyncapi.parser import load_asyncapi_project
from forge_doctor_api.analyzers.cache.scan import load_cache_model
from forge_doctor_api.analyzers.clients.graph import client_graph
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.gateway.parser import load_gateway_models
from forge_doctor_api.analyzers.graphql.parser import load_graphql_project
from forge_doctor_api.analyzers.grpc.parser import load_grpc_project
from forge_doctor_api.analyzers.iac.parser import load_infra_model
from forge_doctor_api.analyzers.openapi.graph import contract_graph
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.analyzers.routes.graph import scan_graph
from forge_doctor_api.analyzers.routes.model import RouteScan
from forge_doctor_api.analyzers.runtime.loader import (
    RuntimeProject,
    load_runtime_project,
)
from forge_doctor_api.analyzers.version.detect import detect_version_model
from forge_doctor_api.change.blast import BlastRadiusReport, blast_radius
from forge_doctor_api.checks.apisec.engine import run_security_checks
from forge_doctor_api.checks.asyncapi.engine import run_async_checks
from forge_doctor_api.checks.compat.engine import ContractDiff, diff_models
from forge_doctor_api.checks.drift.engine import contract_drift
from forge_doctor_api.checks.graphql.engine import run_graphql_checks
from forge_doctor_api.checks.grpc.engine import run_grpc_checks
from forge_doctor_api.checks.oas.engine import run_openapi_checks
from forge_doctor_api.checks.observability.engine import (
    run_observability_checks,
)
from forge_doctor_api.checks.perf.engine import run_perf_checks
from forge_doctor_api.checks.relapi.engine import run_reliability_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.discovery import (
    MARKER_ASYNCAPI,
    MARKER_GRAPHQL,
    MARKER_OPENAPI,
    MARKER_PROTO,
    MARKER_SWAGGER,
    ArtifactClass,
    discover,
)
from forge_doctor_api.core.evidence_store import build_evidence_store
from forge_doctor_api.core.gate import (
    GateCategory,
    GateConfigError,
    GateFailure,
    evaluate_gate,
)
from forge_doctor_api.core.graph import GraphError, ServiceGraph
from forge_doctor_api.core.models import (
    Finding,
    UnknownFact,
)
from forge_doctor_api.core.plan import AnalyzerId, build_plan
from forge_doctor_api.core.report import DomainSummary
from forge_doctor_api.knowledge import knowledge_versions
from forge_doctor_api.knowledge.capability import (
    DetectedCapability,
    detect_capabilities,
)
from forge_doctor_api.perf.fanout import FanoutSignal, FanoutStatus, fanout_signals
from forge_doctor_api.policy.engine import evaluate_policies
from forge_doctor_api.policy.loader import load_policies
from forge_doctor_api.policy.ownership import resolve_ownership
from forge_doctor_api.policy.rules import RuleContext
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.report import DoctorReport
from forge_doctor_api.safefix.classify import classify_findings
from forge_doctor_api.security import load_security_model
from forge_doctor_api.twin.assemble import assemble_twin

# Backward-compatible names (pre-unification exports).
ScanReport = DoctorReport
_GateConfigError = GateConfigError

__all__ = [
    "GateCategory",
    "GateConfigError",
    "GateFailure",
    "ScanReport",
    "_GateConfigError",
    "evaluate_gate",
    "export_scan",
    "scan_project",
]


def _files_marked(
    inventory: Any, *markers: str
) -> list[str]:
    """Non-vendored paths whose strong markers include any of `markers`."""
    return [
        a.path for a in inventory.artifacts
        if not a.vendored and any(m in a.markers for m in markers)
    ]


def _merge_graph(target: ServiceGraph, other: ServiceGraph) -> None:
    for entity in other.entities():
        try:
            target.add_entity(entity)
        except GraphError:
            continue
    for rel in other.relationships():
        try:
            target.add_relationship(rel)
        except GraphError:
            continue


def scan_project(
    context: ProjectContext,
    *,
    before: ProjectContext | None = None,
    extra_policy: ProjectContext | None = None,
    today: date | None = None,
    keep_spans: bool = False,
) -> DoctorReport:
    """Run the unified deterministic pipeline; attach the diff when given."""
    inventory = discover(context)
    store = build_evidence_store(context, inventory)
    plan = build_plan(inventory)
    all_files = [
        a.path for a in inventory.artifacts if not a.vendored
    ]
    service = context.root.name

    findings: list[Finding] = []
    unknowns: list[UnknownFact] = []
    graphs = ServiceGraph()

    # -- contracts -----------------------------------------------------------
    openapi = load_openapi_project(
        context, _files_marked(inventory, MARKER_OPENAPI, MARKER_SWAGGER))
    if openapi.documents:
        findings.extend(run_openapi_checks(openapi))
    _merge_graph(graphs, contract_graph(openapi))

    graphql = None
    if plan.enabled(AnalyzerId.GRAPHQL):
        graphql = load_graphql_project(
            context, _files_marked(inventory, MARKER_GRAPHQL))
        if graphql.documents:
            findings.extend(run_graphql_checks(graphql))
    grpc = None
    if plan.enabled(AnalyzerId.GRPC):
        grpc = load_grpc_project(
            context, _files_marked(inventory, MARKER_PROTO))
        if grpc.files:
            findings.extend(run_grpc_checks(grpc))
    asyncapi = None
    if plan.enabled(AnalyzerId.ASYNCAPI):
        asyncapi = load_asyncapi_project(
            context, _files_marked(inventory, MARKER_ASYNCAPI))
        if asyncapi.documents:
            findings.extend(run_async_checks(asyncapi))

    # -- source ---------------------------------------------------------------
    routes: RouteScan | None = None
    if plan.enabled(AnalyzerId.ROUTES):
        try:
            routes = FastApiAdapter().scan(
                context, service, inventory.files_in(ArtifactClass.SOURCE))
        except Exception:
            routes = None
            unknowns.append(UnknownFact(
                subject="routes",
                missing="framework route scan",
                resolution="route adapter failed; implementation-side "
                "evidence is absent",
            ))
        if routes is not None:
            _merge_graph(graphs, scan_graph(routes))
            unknowns.extend(routes.unknowns)

    clients = None
    if plan.enabled(AnalyzerId.CLIENTS):
        clients = scan_clients(
            context, inventory.files_in(ArtifactClass.CLIENT))
        unknowns.extend(clients.unknowns)
        _merge_graph(graphs, client_graph(clients))

    # -- config/config-plane models -------------------------------------------
    sec_files = inventory.files_in(
        ArtifactClass.SOURCE, ArtifactClass.CONFIG)
    security = load_security_model(
        context, sec_files, openapi=openapi, routes=routes)
    findings.extend(run_security_checks(security, openapi))

    reliability = load_reliability_model(context, inventory.files_in(
        ArtifactClass.CONFIG, ArtifactClass.IAC))
    findings.extend(run_reliability_checks(reliability))

    cache = None
    if plan.enabled(AnalyzerId.CACHE):
        cache = load_cache_model(
            context, inventory.files_in(ArtifactClass.CONFIG),
            openapi=openapi)
        unknowns.extend(cache.unknowns)

    # -- infrastructure --------------------------------------------------------
    gateways: tuple[Any, ...] = ()
    meshes: tuple[Any, ...] = ()
    if plan.enabled(AnalyzerId.GATEWAY):
        gateways, meshes, gw_unknowns = load_gateway_models(
            context, inventory.files_in(
                ArtifactClass.GATEWAY, ArtifactClass.MESH,
                ArtifactClass.IAC))
        unknowns.extend(gw_unknowns)

    infra = None
    if plan.enabled(AnalyzerId.IAC):
        infra = load_infra_model(
            context, inventory.files_in(ArtifactClass.IAC))
        unknowns.extend(infra.unknowns)

    # -- runtime ---------------------------------------------------------------
    runtime: RuntimeProject | None = None
    if plan.enabled(AnalyzerId.RUNTIME):
        runtime = load_runtime_project(
            context, inventory.files_in(ArtifactClass.RUNTIME),
            keep_spans=keep_spans)
        findings.extend(run_observability_checks(runtime.observability))
        findings.extend(run_perf_checks(runtime.executions))
        unknowns.extend(runtime.unknowns)

    # -- correlation ------------------------------------------------------------
    drift = None
    if openapi.documents and routes is not None and routes.routes:
        drift = contract_drift(openapi, routes)
        findings.extend(drift.findings)

    inputs_present = sum([
        bool(openapi.documents),
        bool(routes and routes.routes),
        bool(runtime and runtime.executions),
        bool(reliability.retry_policies or reliability.timeouts
             or reliability.objectives),
        bool(security.auth_schemes or security.authorization),
    ])
    twin = assemble_twin(
        openapi=openapi if openapi.documents else None,
        routes=routes,
        reliability=reliability,
        executions=runtime.executions if runtime else None,
        security=security,
    ) if inputs_present >= 2 else None
    if twin is not None:
        unknowns.extend(twin.unknowns)

    capabilities: tuple[DetectedCapability, ...] = ()
    if plan.enabled(AnalyzerId.VERSION) or openapi.documents:
        cap_report = detect_capabilities(
            openapi=openapi if openapi.documents else None,
            graphql=graphql,
            grpc=grpc,
            asyncapi=asyncapi,
            reliability=reliability,
            security=security,
        )
        capabilities = cap_report.capabilities
        unknowns.extend(cap_report.unknowns)

    # -- policies ----------------------------------------------------------------
    policy_set = load_policies(context, inventory.files_in(
        ArtifactClass.POLICY))
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
        ownership = resolve_ownership(context, all_files, openapi)
        findings.extend(evaluate_policies(
            policy_set,
            RuleContext(openapi=openapi, security=security,
                        reliability=reliability, version=version,
                        ownership=ownership),
            today or date.min,
        ))

    # -- fan-out signals (§59) -----------------------------------------------------
    fanout: tuple[FanoutSignal, ...] = ()
    if routes is not None and clients is not None:
        fanout = fanout_signals(
            routes, clients,
            runtime.executions if runtime else ())
        unknowns.extend(u for s in fanout for u in s.unknowns)

    # -- diff + impact --------------------------------------------------------------
    diff: ContractDiff | None = None
    before_model: OpenApiProjectModel | None = None
    if before is not None:
        before_model = load_openapi_project(before)
        diff = diff_models(before_model, openapi)
        findings.extend(diff.findings)

    blast: BlastRadiusReport | None = None
    if diff is not None and before_model is not None and clients is not None:
        blast = blast_radius(diff, before_model, clients)
        unknowns.extend(blast.unknowns)

    findings_sorted = tuple(sorted(
        findings, key=lambda f: (f.id, f.entity_ids, f.description)))
    unknowns.extend(
        UnknownFact(
            subject=r.ref,
            missing="external reference content",
            resolution="provide the referenced document locally",
        )
        for r in openapi.unresolved_external_refs
    )

    analysis_rev = hashlib.sha256(
        json.dumps(
            [e.sha256 for e in store.entries],
            sort_keys=True,
        ).encode()
    ).hexdigest()

    return DoctorReport(
        tool_version=_tool_version(),
        knowledge_versions=tuple(sorted(knowledge_versions().items())),
        project=service,
        inventory=inventory,
        plan=plan,
        analysis_rev=analysis_rev,
        contracts=_contracts_summary(openapi),
        routes=_routes_summary(routes),
        clients=_clients_summary(clients),
        graph=_graph_summary(graphs),
        gateway=_gateway_summary(gateways),
        mesh=_mesh_summary(meshes),
        infrastructure=_infra_summary(infra),
        cache=_cache_summary(cache),
        runtime=_runtime_summary(runtime),
        security=_security_summary(security),
        reliability=_reliability_summary(reliability),
        policies=_policy_summary(policy_set),
        twin=_twin_summary(twin),
        fanout=_fanout_summary(fanout),
        capabilities=capabilities,
        findings=findings_sorted,
        unknowns=tuple(unknowns),
        operations=tuple(
            f"{o.method.upper()} {o.path}" for o in openapi.operations),
        changes=tuple(
            f"{c.classification.value}:{c.kind}:{c.subject}"
            for c in diff.changes
        ) if diff is not None else (),
        impact=_impact_summary(blast),
        remediation_candidates=tuple(
            c.target for c in classify_findings(findings_sorted).candidates),
        diff=diff,
    )


def _tool_version() -> str:
    from forge_doctor_api import __version__
    return __version__


def _contracts_summary(openapi: OpenApiProjectModel) -> DomainSummary | None:
    if not openapi.documents:
        return None
    return DomainSummary(
        counts=(
            ("documents", len(openapi.documents)),
            ("operations", len(openapi.operations)),
            ("schemas", len(openapi.schemas)),
            ("unresolved_refs", len(openapi.unresolved_external_refs)),
        ),
        ids=tuple(d.location.path for d in openapi.documents),
        summaries=tuple(
            f"{d.title or d.location.path} {d.api_version or ''}".strip()
            for d in openapi.documents
        ),
    )


def _routes_summary(routes: RouteScan | None) -> DomainSummary | None:
    if routes is None:
        return None
    return DomainSummary(
        counts=(
            ("routes", len(routes.routes)),
            ("attributions", len(routes.attributions)),
        ),
        ids=tuple(
            f"{r.method} {r.path}" for r in routes.routes),
        summaries=(f"service={routes.service}",),
        unknowns=len(routes.unknowns),
    )


def _clients_summary(clients: Any) -> DomainSummary | None:
    if clients is None:
        return None
    return DomainSummary(
        counts=(
            ("clients", len(clients.clients)),
            ("call_sites", len(clients.call_sites)),
        ),
        ids=clients.clients,
        unknowns=len(clients.unknowns),
    )


def _graph_summary(graphs: ServiceGraph) -> DomainSummary | None:
    entities = tuple(graphs.entities())
    if not entities:
        return None
    rels = tuple(graphs.relationships())
    service_ids = tuple(sorted(
        e.id for e in entities if e.kind == "service"))
    return DomainSummary(
        counts=(
            ("entities", len(entities)),
            ("relationships", len(rels)),
        ),
        ids=service_ids,
    )


def _gateway_summary(gateways: tuple[Any, ...]) -> DomainSummary | None:
    if not gateways:
        return None
    return DomainSummary(
        counts=(
            ("gateways", len(gateways)),
            ("routes", sum(len(g.routes) for g in gateways)),
            ("upstreams", sum(len(g.upstreams) for g in gateways)),
        ),
        ids=tuple(sorted({g.source.path for g in gateways})),
        unknowns=sum(len(g.unknowns) for g in gateways),
    )


def _mesh_summary(meshes: tuple[Any, ...]) -> DomainSummary | None:
    if not meshes:
        return None
    return DomainSummary(
        counts=(
            ("meshes", len(meshes)),
            ("routing", sum(len(m.routing) for m in meshes)),
        ),
        ids=tuple(sorted({str(m.vendor) for m in meshes})),
        unknowns=sum(len(m.unknowns) for m in meshes),
    )


def _infra_summary(infra: Any) -> DomainSummary | None:
    if infra is None:
        return None
    return DomainSummary(
        counts=(
            ("kubernetes", len(infra.kubernetes)),
            ("iac", len(infra.iac)),
            ("chains", len(infra.chains)),
        ),
        ids=tuple(sorted({r.name for r in infra.kubernetes})),
        unknowns=len(infra.unknowns),
    )


def _cache_summary(cache: Any) -> DomainSummary | None:
    if cache is None or not (cache.policies or cache.risks):
        return None
    return DomainSummary(
        counts=(
            ("policies", len(cache.policies)),
            ("risks", len(cache.risks)),
        ),
        unknowns=len(cache.unknowns),
    )


def _runtime_summary(runtime: RuntimeProject | None) -> DomainSummary | None:
    if runtime is None:
        return None
    obs = runtime.observability
    return DomainSummary(
        counts=(
            ("traces", len(runtime.traces)),
            ("executions", len(runtime.executions)),
            ("spans", obs.span_count),
            ("requests", obs.request_count),
        ),
        ids=obs.operation_names,
        unknowns=len(runtime.unknowns),
    )


def _security_summary(security: Any) -> DomainSummary | None:
    if not (security.auth_schemes or security.authorization
            or security.rate_limits or security.cors
            or security.external_apis):
        return None
    return DomainSummary(
        counts=(
            ("auth_schemes", len(security.auth_schemes)),
            ("authorization", len(security.authorization)),
            ("rate_limits", len(security.rate_limits)),
            ("cors", len(security.cors)),
            ("external_apis", len(security.external_apis)),
        ),
        ids=tuple(a.name for a in security.auth_schemes),
    )


def _reliability_summary(reliability: Any) -> DomainSummary | None:
    if not (reliability.retry_policies or reliability.timeouts
            or reliability.circuit_breakers or reliability.objectives):
        return None
    return DomainSummary(
        counts=(
            ("retry_policies", len(reliability.retry_policies)),
            ("timeouts", len(reliability.timeouts)),
            ("circuit_breakers", len(reliability.circuit_breakers)),
            ("objectives", len(reliability.objectives)),
        ),
    )


def _policy_summary(policy_set: Any) -> DomainSummary | None:
    if not (policy_set.policies or policy_set.exceptions
            or policy_set.issues):
        return None
    return DomainSummary(
        counts=(
            ("policies", len(policy_set.policies)),
            ("exceptions", len(policy_set.exceptions)),
            ("issues", len(policy_set.issues)),
        ),
        ids=tuple(p.id for p in policy_set.policies),
        unknowns=len(policy_set.unknowns),
    )


def _twin_summary(twin: Any) -> DomainSummary | None:
    if twin is None:
        return None
    return DomainSummary(
        counts=(
            ("states_present", sum(1 for s in twin.states if s.present)),
            ("states", len(twin.states)),
        ),
        ids=tuple(s.state.value for s in twin.states if s.present),
        unknowns=len(twin.unknowns),
    )


def _fanout_summary(signals: tuple[FanoutSignal, ...]) -> DomainSummary | None:
    if not signals:
        return None
    confirmed = sum(1 for s in signals if s.status is FanoutStatus.CONFIRMED)
    return DomainSummary(
        counts=(
            ("signals", len(signals)),
            ("confirmed", confirmed),
            ("candidates", len(signals) - confirmed),
        ),
        ids=tuple(s.subject for s in signals),
        unknowns=sum(len(s.unknowns) for s in signals),
    )


def _impact_summary(blast: BlastRadiusReport | None) -> DomainSummary | None:
    if blast is None:
        return None
    return DomainSummary(
        counts=(
            ("nodes", len(blast.nodes)),
            ("affected_clients", len(blast.affected_clients)),
        ),
        ids=blast.affected_clients,
        unknowns=len(blast.unknowns),
    )


def export_scan(report: DoctorReport) -> dict[str, object]:
    """§174 metadata-carrying scan export."""
    return {
        "schema_version": "1.0",
        "tool_version": report.tool_version or _tool_version(),
        "knowledge_versions": dict(report.knowledge_versions)
        or knowledge_versions(),
        "gate_passed": report.gate_passed,
        "gate_failures": [f.to_dict() for f in report.gate_failures],
    }
