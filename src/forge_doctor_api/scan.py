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
import tracemalloc
from datetime import date
from time import perf_counter
from typing import Any

from forge_doctor_api.analyzers.asyncapi.parser import load_asyncapi_project
from forge_doctor_api.analyzers.cache.scan import load_cache_model
from forge_doctor_api.analyzers.clients.graph import client_graph
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.gateway.parser import load_gateway_models
from forge_doctor_api.analyzers.graphql.parser import load_graphql_project
from forge_doctor_api.analyzers.grpc.parser import load_grpc_project
from forge_doctor_api.analyzers.iac.model import InfraModel
from forge_doctor_api.analyzers.iac.parser import load_infra_model
from forge_doctor_api.analyzers.openapi.graph import contract_graph
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import available_adapters
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
from forge_doctor_api.core.cache import AnalysisCache
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
from forge_doctor_api.core.graph import (
    GraphError,
    ServiceGraph,
    export_edges,
)
from forge_doctor_api.core.models import (
    Finding,
    Model,
    ModelError,
    UnknownFact,
    parse_entity_id,
)
from forge_doctor_api.core.plan import AnalyzerId, build_plan
from forge_doctor_api.core.report import DomainSummary
from forge_doctor_api.core.stats import AnalysisStats, AnalyzerStat
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
    stats_timing: bool = False,
    incremental: bool = False,
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

    # spec 066: per-analyzer {ran, artifacts, findings, unknowns};
    # duration_ms only under stats_timing (off the canonical surface).
    stats: list[AnalyzerStat] = []

    def _mark() -> tuple[int, int, float | None, int | None]:
        traced = stats_timing and tracemalloc.is_tracing()
        return (len(findings), len(unknowns),
                perf_counter() if stats_timing else None,
                tracemalloc.get_traced_memory()[0] if traced else None)

    def _rec(name: str, ran: bool, artifacts: int,
             mark: tuple[int, int, float | None, int | None]) -> None:
        f0, u0, t0, m0 = mark
        stats.append(AnalyzerStat(
            analyzer=name, ran=ran, artifacts=artifacts,
            findings=len(findings) - f0,
            unknowns=len(unknowns) - u0,
            duration_ms=((perf_counter() - t0) * 1000)
            if t0 is not None else None,
            allocated_bytes=(tracemalloc.get_traced_memory()[0] - m0)
            if m0 is not None else None))

    # spec 065: opt-in analyzer-level model cache. Never stores
    # findings/unknowns — checks always recompute over the models.
    analysis_cache: AnalysisCache | None = (
        AnalysisCache(context.root, tool_version=_tool_version())
        if incremental else None)

    def _shas(files: list[str]) -> list[str]:
        return [s for f in files if (s := store.hash_of(f)) is not None]

    def _cached_load(
        name: str,
        files: list[str],
        config: str,
        load: Any,
        model_cls: type[Model],
    ) -> Any:
        if analysis_cache is None:
            return load()
        shas = _shas(files)
        hit = analysis_cache.get(name, shas, config)
        if hit is not None:
            try:
                return model_cls.from_dict(hit)
            except ModelError:
                pass  # corrupt/stale entry → full analysis
        model = load()
        analysis_cache.put(name, shas, config, model.to_dict())
        return model

    # -- contracts -----------------------------------------------------------
    openapi_files = _files_marked(
        inventory, MARKER_OPENAPI, MARKER_SWAGGER)
    m = _mark()
    openapi: OpenApiProjectModel = _cached_load(
        AnalyzerId.OPENAPI.value, openapi_files, "",
        lambda: load_openapi_project(context, openapi_files),
        OpenApiProjectModel)
    if openapi.documents:
        findings.extend(run_openapi_checks(openapi))
    _merge_graph(graphs, contract_graph(openapi))
    _rec(AnalyzerId.OPENAPI.value, bool(openapi.documents),
         len(openapi_files), m)

    graphql = None
    if plan.enabled(AnalyzerId.GRAPHQL):
        gql_files = _files_marked(inventory, MARKER_GRAPHQL)
        m = _mark()
        graphql = load_graphql_project(context, gql_files)
        if graphql.documents:
            findings.extend(run_graphql_checks(graphql))
        _rec(AnalyzerId.GRAPHQL.value, bool(graphql.documents),
             len(gql_files), m)
    grpc = None
    if plan.enabled(AnalyzerId.GRPC):
        grpc_files = _files_marked(inventory, MARKER_PROTO)
        m = _mark()
        grpc = load_grpc_project(context, grpc_files)
        if grpc.files:
            findings.extend(run_grpc_checks(grpc))
        _rec(AnalyzerId.GRPC.value, bool(grpc.files), len(grpc_files), m)
    asyncapi = None
    if plan.enabled(AnalyzerId.ASYNCAPI):
        async_files = _files_marked(inventory, MARKER_ASYNCAPI)
        m = _mark()
        asyncapi = load_asyncapi_project(context, async_files)
        if asyncapi.documents:
            findings.extend(run_async_checks(asyncapi))
        _rec(AnalyzerId.ASYNCAPI.value, bool(asyncapi.documents),
             len(async_files), m)

    # -- source ---------------------------------------------------------------
    routes: RouteScan | None = None
    if plan.enabled(AnalyzerId.ROUTES):
        m = _mark()
        source_files = inventory.files_in(ArtifactClass.SOURCE)
        try:
            adapters = available_adapters(context, source_files)
        except Exception:
            adapters = ()
        if not adapters:
            unknowns.append(UnknownFact(
                subject="routes",
                missing="recognized framework in source files",
                resolution="no builtin adapter detected the framework; "
                "implementation-side route evidence is absent",
            ))
        scans: list[RouteScan] = []
        for adapter in adapters:
            try:
                scans.append(adapter.discover_routes(
                    context, service, source_files))
            except Exception:
                unknowns.append(UnknownFact(
                    subject=f"routes:{adapter.name}",
                    missing="framework route scan",
                    resolution="route adapter failed; partial route "
                    "evidence may be absent",
                ))
        if scans:
            routes = RouteScan(
                service=service,
                routes=tuple(sorted(
                    {r for s in scans for r in s.routes},
                    key=lambda r: (r.method, r.path, r.handler))),
                attributions=tuple(sorted(
                    {a for s in scans for a in s.attributions},
                    key=lambda a: a.path)),
                unknowns=tuple(sorted(
                    {u for s in scans for u in s.unknowns},
                    key=lambda u: (u.subject, u.missing))),
            )
            _merge_graph(graphs, scan_graph(routes))
            unknowns.extend(routes.unknowns)
        _rec(AnalyzerId.ROUTES.value, bool(routes and routes.routes),
             len(source_files), m)

    clients = None
    if plan.enabled(AnalyzerId.CLIENTS):
        client_files = inventory.files_in(ArtifactClass.CLIENT)
        m = _mark()
        clients = scan_clients(context, client_files)
        unknowns.extend(clients.unknowns)
        _merge_graph(graphs, client_graph(clients))
        _rec(AnalyzerId.CLIENTS.value, bool(clients.clients),
             len(client_files), m)

    # -- config/config-plane models -------------------------------------------
    sec_files = inventory.files_in(
        ArtifactClass.SOURCE, ArtifactClass.CONFIG)
    m = _mark()
    security = load_security_model(
        context, sec_files, openapi=openapi, routes=routes)
    findings.extend(run_security_checks(security, openapi))
    _rec(AnalyzerId.SECURITY.value, True, len(sec_files), m)

    rel_files = inventory.files_in(
        ArtifactClass.CONFIG, ArtifactClass.IAC)
    m = _mark()
    reliability = load_reliability_model(context, rel_files)
    findings.extend(run_reliability_checks(reliability))
    _rec(AnalyzerId.RELIABILITY.value, True, len(rel_files), m)

    cache = None
    cache_graph: Any = None
    if plan.enabled(AnalyzerId.CACHE):
        cache_files = inventory.files_in(ArtifactClass.CONFIG)
        m = _mark()
        cache = load_cache_model(context, cache_files, openapi=openapi)
        unknowns.extend(cache.unknowns)
        if openapi.documents:
            from forge_doctor_api.analyzers.cache.graph import (
                build_cache_graph,
            )
            cache_graph, cache_findings = build_cache_graph(
                cache, openapi)
            findings.extend(cache_findings)
        _rec(AnalyzerId.CACHE.value, bool(cache.policies),
             len(cache_files), m)

    # -- infrastructure --------------------------------------------------------
    gateways: tuple[Any, ...] = ()
    meshes: tuple[Any, ...] = ()
    if plan.enabled(AnalyzerId.GATEWAY):
        gw_files = inventory.files_in(
            ArtifactClass.GATEWAY, ArtifactClass.MESH,
            ArtifactClass.IAC)
        m = _mark()
        gateways, meshes, gw_unknowns = load_gateway_models(
            context, gw_files)
        unknowns.extend(gw_unknowns)
        _rec(AnalyzerId.GATEWAY.value, bool(gateways or meshes),
             len(gw_files), m)

    # spec 062: depth checks over *evidenced* caller->callee edges only
    # (CALLS relationships + resolved gateway route targets). Name
    # similarity never creates a hop.
    from forge_doctor_api.checks.relapi.engine import run_depth_checks
    chain_edges: list[tuple[str, str]] = []
    for r in graphs.relationships():
        if r.kind == "CALLS":
            try:
                chain_edges.append((
                    parse_entity_id(r.source_id)[2],
                    parse_entity_id(r.target_id)[2]))
            except ModelError:
                continue
    for gw in gateways:
        for rt in gw.routes:
            if rt.service:
                chain_edges.append((gw.dialect.value, rt.service))
    findings.extend(run_depth_checks(reliability, tuple(chain_edges)))

    infra = None
    if plan.enabled(AnalyzerId.IAC):
        iac_files = inventory.files_in(ArtifactClass.IAC)
        m = _mark()
        infra = _cached_load(
            AnalyzerId.IAC.value, iac_files, "",
            lambda: load_infra_model(context, iac_files),
            InfraModel)
        unknowns.extend(infra.unknowns)
        _rec(AnalyzerId.IAC.value, bool(
            infra.iac or infra.kubernetes or infra.chains),
            len(iac_files), m)

    # -- runtime ---------------------------------------------------------------
    runtime: RuntimeProject | None = None
    if plan.enabled(AnalyzerId.RUNTIME):
        rt_files = inventory.files_in(ArtifactClass.RUNTIME)
        m = _mark()
        runtime = _cached_load(
            AnalyzerId.RUNTIME.value, rt_files,
            f"keep_spans={keep_spans}",
            lambda: load_runtime_project(
                context, rt_files, keep_spans=keep_spans),
            RuntimeProject)
        findings.extend(run_observability_checks(runtime.observability))
        findings.extend(run_perf_checks(runtime.executions))
        unknowns.extend(runtime.unknowns)
        _rec(AnalyzerId.RUNTIME.value, bool(
            runtime.traces or runtime.executions),
            len(rt_files), m)

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

    m = _mark()
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
    _rec(AnalyzerId.VERSION.value, bool(capabilities), 0, m)

    # -- policies ----------------------------------------------------------------
    m = _mark()
    pol_files = inventory.files_in(ArtifactClass.POLICY)
    policy_set = load_policies(context, pol_files)
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
    _rec(AnalyzerId.POLICY.value, bool(
        policy_set.policies or policy_set.exceptions
        or policy_set.issues), len(pol_files), m)

    # -- fan-out signals (§59) -----------------------------------------------------
    fanout: tuple[FanoutSignal, ...] = ()
    m = _mark()
    if routes is not None and clients is not None:
        fanout = fanout_signals(
            routes, clients,
            runtime.executions if runtime else ())
        unknowns.extend(u for s in fanout for u in s.unknowns)
    _rec("fanout", bool(fanout), 0, m)

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

    # -- migration graph (spec 060) ------------------------------------------
    migration: Any = None
    migration_path_count = 0
    m = _mark()
    if openapi.documents:
        from forge_doctor_api.migrate.graph import (
            build_migration_graph,
            migration_paths,
        )
        migration = build_migration_graph(openapi, clients)
        unknowns.extend(migration.unknowns)
        migration_path_count = len(migration_paths(migration))
    _rec("migration", migration is not None, 0, m)

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

    analysis_stats = AnalysisStats(
        analyzers=tuple(stats),
        total_findings=len(findings_sorted),
        total_unknowns=len(unknowns))

    return DoctorReport(
        tool_version=_tool_version(),
        knowledge_versions=tuple(sorted(knowledge_versions().items())),
        project=service,
        inventory=inventory,
        plan=plan,
        analysis_rev=analysis_rev,
        stats=analysis_stats,
        contracts=_contracts_summary(openapi),
        routes=_routes_summary(routes),
        clients=_clients_summary(clients),
        graph=_graph_summary(graphs),
        graph_edges=export_edges(graphs),
        gateway=_gateway_summary(gateways),
        mesh=_mesh_summary(meshes),
        infrastructure=_infra_summary(infra),
        cache=_cache_summary(cache, cache_graph),
        migration=_migration_summary(migration, migration_path_count),
        runtime=_runtime_summary(runtime),
        security=_security_summary(security),
        reliability=_reliability_summary(reliability),
        policies=_policy_summary(policy_set),
        twin=_twin_summary(twin),
        fanout=_fanout_summary(fanout),
        capabilities=capabilities,
        findings=findings_sorted,
        unknowns=tuple(unknowns),
        operations=tuple(sorted(
            f"{o.method.upper()} {o.path}" for o in openapi.operations)),
        changes=tuple(sorted(
            f"{c.classification.value}:{c.kind}:{c.subject}"
            for c in diff.changes
        )) if diff is not None else (),
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
        digests=tuple(sorted(
            (o.identity or f"{o.method} {o.path}",
             hashlib.sha256(o.to_json().encode("utf-8")).hexdigest()[:16])
            for o in openapi.operations)),
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


def _cache_summary(cache: Any, cache_graph: Any = None) -> DomainSummary | None:
    if cache is None or not (cache.policies or cache.risks):
        return None
    edge_count = len(cache_graph.edges) if cache_graph is not None else 0
    return DomainSummary(
        counts=(
            ("policies", len(cache.policies)),
            ("risks", len(cache.risks)),
            ("graph_edges", edge_count),
        ),
        ids=(tuple(cache_graph.cached_operations)
             if cache_graph is not None else ()),
        unknowns=len(cache.unknowns),
    )


def _migration_summary(
    graph: Any, path_count: int,
) -> DomainSummary | None:
    if graph is None:
        return None
    return DomainSummary(
        counts=(
            ("units", len(graph.nodes)),
            ("edges", len(graph.edges)),
            ("paths", path_count),
        ),
        ids=tuple(n.unit_id for n in graph.nodes),
        unknowns=len(graph.unknowns),
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
