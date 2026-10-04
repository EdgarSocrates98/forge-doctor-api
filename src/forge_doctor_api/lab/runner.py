"""§98-§101, §199 scenario runner — pipelines over a fixture tree.

Every analyzer's strong-marker detection gate decides what it sees;
weak-marker files simply produce nothing (§101). `expected.yaml` is
excluded from the observed file set. `run:` restricts which pipelines
execute; empty means the default deterministic set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from forge_doctor_api.analyzers.asyncapi.parser import load_asyncapi_project
from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.graphql.parser import load_graphql_project
from forge_doctor_api.analyzers.grpc.parser import load_grpc_project
from forge_doctor_api.analyzers.openapi.graph import contract_graph
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.analyzers.routes.graph import scan_graph
from forge_doctor_api.analyzers.runtime.loader import load_runtime_project
from forge_doctor_api.analyzers.version import detect_version_model
from forge_doctor_api.checks.apisec.engine import run_security_checks
from forge_doctor_api.checks.asyncapi.engine import run_async_checks
from forge_doctor_api.checks.client.engine import client_impact
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.compat.engine import diff_models
from forge_doctor_api.checks.graphql.engine import run_graphql_checks
from forge_doctor_api.checks.grpc.engine import run_grpc_checks
from forge_doctor_api.checks.oas.engine import run_openapi_checks
from forge_doctor_api.checks.observability.engine import run_observability_checks
from forge_doctor_api.checks.perf.engine import run_perf_checks
from forge_doctor_api.checks.relapi.engine import run_reliability_checks
from forge_doctor_api.core.context import ContextError, ProjectContext
from forge_doctor_api.core.graph import ServiceGraph
from forge_doctor_api.core.models import Finding
from forge_doctor_api.lab.model import LabScenario
from forge_doctor_api.policy import (
    RuleContext,
    evaluate_policies,
    load_policies,
    resolve_ownership,
)
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.security import load_security_model

_DEFAULT_RUN = (
    "openapi", "security", "reliability", "clients", "runtime",
    "graphql", "grpc", "asyncapi", "policy",
)


@dataclass(kw_only=True)
class LabObservations:
    """Everything a scenario produced, normalized for comparison."""

    findings: list[Finding] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    clients: list[str] = field(default_factory=list)
    breaking: list[str] = field(default_factory=list)
    runtime_signals: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _sub_ctx(ctx: ProjectContext, sub: str | None) -> ProjectContext:
    if sub is None or sub == ".":
        return ctx
    return ProjectContext.from_root(ctx.resolve(sub), clock=ctx.clock)


def _route_scans(ctx: ProjectContext) -> tuple[ServiceGraph, ...]:
    """FastAPI route scans (spec 006 adapter) for expected-entity checks."""
    try:
        scan = FastApiAdapter().scan(ctx, service=ctx.root.name)
    except (ContextError, OSError, ValueError):
        return ()
    return (scan_graph(scan),) if scan.routes else ()


def run_scenario(context: ProjectContext, scenario: LabScenario) -> LabObservations:
    """Run the scenario's pipelines and collect observations."""
    ctx = _sub_ctx(context, scenario.path)
    files = [
        f for f in ctx.iter_files()
        if Path(f).name not in ("expected.yaml", "expected.yml")
    ]
    run = set(scenario.run) if scenario.run else set(_DEFAULT_RUN)
    obs = LabObservations()

    openapi: OpenApiProjectModel | None = None
    if run & {"openapi", "security", "diff", "policy"}:
        openapi = load_openapi_project(ctx)
        obs.issues.extend(f"{i.code}:{i.message}" for i in openapi.issues)
    if "openapi" in run and openapi is not None:
        obs.findings.extend(run_openapi_checks(openapi))
        graph = contract_graph(openapi)
        obs.entities.extend(f"{e.kind}:{e.name}" for e in graph.entities())
        obs.edges.extend(
            f"{r.kind}:{r.source_id}->{r.target_id}" for r in graph.relationships()
        )
        for route_graph in _route_scans(ctx):
            obs.entities.extend(f"{e.kind}:{e.name}" for e in route_graph.entities())
            obs.edges.extend(
                f"{r.kind}:{r.source_id}->{r.target_id}"
                for r in route_graph.relationships()
            )

    clients: ApiClientModel | None = None
    if "clients" in run or scenario.diff_old:
        clients = scan_clients(ctx, files)
        obs.clients.extend(clients.clients)
        obs.issues.extend(f"{u.subject}:{u.missing}" for u in clients.unknowns)

    security = None
    if "security" in run or "policy" in run:
        security = load_security_model(ctx, files, openapi=openapi)
    if "security" in run and openapi is not None and security is not None:
        obs.findings.extend(run_security_checks(security, openapi))

    reliability = None
    if "reliability" in run or "policy" in run:
        reliability = load_reliability_model(ctx, files)
    if "reliability" in run and reliability is not None:
        obs.findings.extend(
            run_reliability_checks(reliability, tuple(scenario.hops) or None)
        )

    if "runtime" in run:
        rt = load_runtime_project(ctx, files, keep_spans=False)
        obs.findings.extend(run_observability_checks(rt.observability))
        obs.findings.extend(run_perf_checks(rt.executions))
        obs.runtime_signals.extend(sorted(rt.observability.signals))

    if "graphql" in run:
        gql = load_graphql_project(ctx, files)
        if gql.documents:
            obs.findings.extend(run_graphql_checks(gql))
    if "grpc" in run:
        grpc = load_grpc_project(ctx, files)
        if grpc.files:
            obs.findings.extend(run_grpc_checks(grpc))
    if "asyncapi" in run:
        async_model = load_asyncapi_project(ctx)
        if async_model.documents:
            obs.findings.extend(run_async_checks(async_model))

    if "policy" in run:
        policy_set = load_policies(ctx, files)
        today = (
            date.fromisoformat(scenario.today)
            if scenario.today
            else date.min
        )
        rule_ctx = RuleContext(
            openapi=openapi,
            security=security,
            reliability=reliability,
            version=detect_version_model(openapi) if openapi else None,
            ownership=resolve_ownership(ctx, files, openapi),
        )
        obs.findings.extend(evaluate_policies(policy_set, rule_ctx, today))

    if scenario.diff_old and scenario.diff_new:
        old_model = load_openapi_project(_sub_ctx(ctx, scenario.diff_old))
        new_model = load_openapi_project(_sub_ctx(ctx, scenario.diff_new))
        diff = diff_models(old_model, new_model)
        obs.breaking.extend(
            c.subject for c in diff.changes
            if c.classification is not CompatibilityClass.NON_BREAKING
        )
        if clients is not None:
            obs.findings.extend(client_impact(diff, clients, old_model).findings)

    obs.findings.sort(key=lambda f: (f.id, f.description))
    obs.entities.sort()
    obs.edges.sort()
    obs.clients = sorted(set(obs.clients))
    return obs
