"""Command-line interface. Command names follow §159-§166."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from forge_doctor_api import __version__
from forge_doctor_api.analyzers.clients.graph import client_graph
from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.openapi.graph import contract_graph
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.analyzers.routes.graph import scan_graph
from forge_doctor_api.analyzers.runtime.execution import (
    RequestExecution,
    executions_from_summaries,
    executions_from_traces,
)
from forge_doctor_api.analyzers.runtime.loader import (
    detect_adapter,
    load_runtime_project,
)
from forge_doctor_api.analyzers.runtime.model import RequestSummary
from forge_doctor_api.analyzers.version.detect import detect_version_model
from forge_doctor_api.change import (
    BlastRadiusReport,
    blast_radius,
    change_report,
    config_events,
    pr_summary,
)
from forge_doctor_api.change.model import ChangeEvent
from forge_doctor_api.checks.apisec import run_security_checks
from forge_doctor_api.checks.compat import ContractDiff, diff_models, semantic_fingerprint
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.checks.perf import run_perf_checks
from forge_doctor_api.checks.relapi import run_reliability_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.export import export_findings
from forge_doctor_api.core.graph import GraphError, ServiceGraph
from forge_doctor_api.core.models import UnknownFact
from forge_doctor_api.perf.baseline import build_baselines
from forge_doctor_api.reliability import (
    ApiReliabilityModel,
    RetryPolicy,
    TimeoutConfig,
    load_reliability_model,
)
from forge_doctor_api.security import load_security_model
from forge_doctor_api.security.model import SensitiveBusinessFlow

NOT_IMPLEMENTED_EXIT_CODE = 3

_stderr = Console(stderr=True, highlight=False)

app = typer.Typer(
    name="forge-doctor-api",
    help="Deterministic, offline-first API architecture intelligence.",
    no_args_is_help=True,
    add_completion=False,
)
contract_app = typer.Typer(help="Inspect, diff and check API contracts.", no_args_is_help=True)
runtime_app = typer.Typer(help="Analyze exported runtime evidence.", no_args_is_help=True)
security_app = typer.Typer(help="Passive security analysis.", no_args_is_help=True)
reliability_app = typer.Typer(help="Reliability analysis.", no_args_is_help=True)

app.add_typer(contract_app, name="contract")
app.add_typer(runtime_app, name="runtime")
app.add_typer(security_app, name="security")
app.add_typer(reliability_app, name="reliability")


def _not_implemented(command: str) -> None:
    _stderr.print(f"forge-doctor-api {command}: not implemented")
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT_CODE)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"forge-doctor-api {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Deterministic, offline-first API architecture intelligence."""


@app.command()
def scan() -> None:
    """Scan a project for API evidence."""
    _not_implemented("scan")


@app.command()
def inventory() -> None:
    """List services, APIs, operations, protocols, versions and owners."""
    _not_implemented("inventory")


@contract_app.command("inspect")
def contract_inspect() -> None:
    """Inspect an API contract."""
    _not_implemented("contract inspect")


_console = Console(highlight=False)


def _load_model(target: str) -> tuple[OpenApiProjectModel | None, str]:
    path = Path(target).resolve()
    if path.is_dir():
        return load_openapi_project(ProjectContext.from_root(path)), path.name
    if path.is_file():
        return (
            load_openapi_project(ProjectContext.from_root(path.parent), [path.name]),
            path.name,
        )
    return None, target


def _diff_report(old: str, new: str) -> ContractDiff | None:
    old_model, _ = _load_model(old)
    new_model, _ = _load_model(new)
    if old_model is None or new_model is None:
        _stderr.print(f"cannot read contract input: {old if old_model is None else new}")
        return None
    return diff_models(old_model, new_model)


def _load_side(target: str) -> tuple[OpenApiProjectModel | None, ProjectContext | None]:
    """Load a contract model; directory inputs also expose their context for config diffs."""
    path = Path(target).resolve()
    if path.is_dir():
        ctx = ProjectContext.from_root(path)
        return load_openapi_project(ctx), ctx
    if path.is_file():
        return load_openapi_project(ProjectContext.from_root(path.parent), [path.name]), None
    return None, None


def _config_events_for(
    old: OpenApiProjectModel,
    new: OpenApiProjectModel,
    old_ctx: ProjectContext | None,
    new_ctx: ProjectContext | None,
) -> tuple[ChangeEvent, ...]:
    """Config-plane diff (§65): only when both sides are directory inputs."""
    if old_ctx is None or new_ctx is None:
        return ()
    old_rel = load_reliability_model(old_ctx, list(old_ctx.iter_files()))
    new_rel = load_reliability_model(new_ctx, list(new_ctx.iter_files()))
    old_sec = load_security_model(old_ctx, list(old_ctx.iter_files()), openapi=old)
    new_sec = load_security_model(new_ctx, list(new_ctx.iter_files()), openapi=new)
    return config_events(
        old_rel, new_rel, old_sec, new_sec,
        detect_version_model(old), detect_version_model(new), old, new,
    )


def _print_events(events: tuple[ChangeEvent, ...], diff: ContractDiff, as_json: bool) -> None:
    if as_json:
        payload = {
            "events": [e.to_dict() for e in events],
            "diff": {
                "changes": [c.to_dict() for c in diff.changes],
                "findings": export_findings(diff.findings).to_dict(),
            },
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not events:
        _console.print("no semantic changes")
        return
    for e in events:
        _console.print(
            f"{e.type.value}  [{e.classification.value}]  {e.kind}  "
            f"{e.subject}  — {Text(e.detail).plain}",
            markup=False,
        )


def _print_pr_summary(
    events: tuple[ChangeEvent, ...],
    affected_clients: tuple[str, ...],
    reliability: ApiReliabilityModel | None,
    extra_unknowns: int,
) -> None:
    s = pr_summary(
        events,
        affected_clients=affected_clients,
        reliability=reliability,
        extra_unknowns=extra_unknowns,
    )
    _console.print("Breaking API changes:", s.breaking_changes)
    _console.print("Affected clients:", s.affected_clients)
    _console.print("New public endpoint:", s.new_public_endpoints)
    _console.print("Authorization changes:", s.authorization_changes)
    _console.print("SLO-relevant dependency changes:", s.slo_relevant_dependency_changes)
    _console.print("Unknowns:", s.unknowns)


def _load_clients(clients_dir: str | None) -> ApiClientModel | None:
    if clients_dir is None:
        return None
    path = Path(clients_dir).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read client source dir: {clients_dir}")
        raise typer.Exit(code=2)
    ctx = ProjectContext.from_root(path)
    return scan_clients(ctx, list(ctx.iter_files()))


def _print_blast(report: BlastRadiusReport, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return
    if not report.nodes:
        _console.print("no impacted operations")
        return
    for node in report.nodes:
        label = f"{node.method} {node.path}".strip() or node.operation
        _console.print(f"{node.change_kind}  {label}  [{node.classification.value}]")
        _console.print(f"  clients: {', '.join(node.clients) if node.clients else 'unknown'}")
        _console.print(f"  services: {', '.join(node.services) if node.services else 'unknown'}")
        paths = ", ".join(node.business_paths) if node.business_paths else "unknown"
        _console.print(f"  business paths: {paths}")
    for unknown in report.unknowns:
        _console.print(f"UNKNOWN: {unknown.subject} — {unknown.missing}")


def _print_diff(diff: ContractDiff, as_json: bool) -> None:
    if as_json:
        payload = {
            "changes": [c.to_dict() for c in diff.changes],
            "findings": export_findings(diff.findings).to_dict(),
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not diff.changes:
        _console.print("no semantic changes")
        return
    table = Table(show_lines=False)
    table.add_column("class", no_wrap=True)
    table.add_column("side", no_wrap=True)
    table.add_column("kind", no_wrap=True)
    table.add_column("subject", no_wrap=True)
    table.add_column("detail")
    for change in diff.changes:
        table.add_row(
            change.classification.value,
            change.side.value,
            change.kind,
            change.subject,
            change.detail,
        )
    _console.print(table)


@contract_app.command("diff")
def contract_diff(
    old: Annotated[str, typer.Argument(help="Old contract file or directory.")],
    new: Annotated[str, typer.Argument(help="New contract file or directory.")],
    semantic: Annotated[
        bool, typer.Option("--semantic", help="Emit the semantic change list.")
    ] = True,
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Diff two API contracts (§66)."""
    diff = _diff_report(old, new)
    if diff is None:
        raise typer.Exit(code=2)
    _print_diff(diff, json_out)


@contract_app.command("compatibility")
def contract_compatibility(
    old: Annotated[str, typer.Argument(help="Old contract file or directory.")],
    new: Annotated[str, typer.Argument(help="New contract file or directory.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Classify contract changes by compatibility (§16, §160)."""
    diff = _diff_report(old, new)
    if diff is None:
        raise typer.Exit(code=2)
    if json_out:
        _print_diff(diff, True)
        return
    counts = {cls: 0 for cls in CompatibilityClass}
    for change in diff.changes:
        counts[change.classification] += 1
    verdict = (
        CompatibilityClass.BREAKING
        if counts[CompatibilityClass.BREAKING]
        else CompatibilityClass.POTENTIALLY_BREAKING
        if counts[CompatibilityClass.POTENTIALLY_BREAKING]
        else CompatibilityClass.UNKNOWN
        if counts[CompatibilityClass.UNKNOWN]
        else CompatibilityClass.NON_BREAKING
    )
    _console.print(f"compatibility verdict: {verdict.value}")
    for cls in CompatibilityClass:
        if counts[cls]:
            _console.print(f"  {cls.value}: {counts[cls]}")
    _print_diff(diff, False)


@app.command("diff")
def semantic_diff(
    old: Annotated[str, typer.Argument(help="Old contract file or directory.")],
    new: Annotated[str, typer.Argument(help="New contract file or directory.")],
    semantic: Annotated[
        bool, typer.Option("--semantic", help="Emit typed change events (§65).")
    ] = True,
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    pr: Annotated[
        bool, typer.Option("--pr", help="Print the §67 PR-intel summary.")
    ] = False,
    clients: Annotated[
        str | None, typer.Option("--clients", help="Directory of client sources (blast radius).")
    ] = None,
) -> None:
    """Semantic contract diff (§66): typed change events + optional PR summary."""
    old_model, old_ctx = _load_side(old)
    new_model, new_ctx = _load_side(new)
    if old_model is None or new_model is None:
        _stderr.print(f"cannot read contract input: {old if old_model is None else new}")
        raise typer.Exit(code=2)
    diff = diff_models(old_model, new_model)
    events = change_report(diff, _config_events_for(old_model, new_model, old_ctx, new_ctx)).events
    if semantic:
        _print_events(events, diff, json_out)
    else:
        _print_diff(diff, json_out)
    if pr:
        client_model = _load_clients(clients)
        report = (
            blast_radius(diff, old_model, client_model)
            if client_model is not None
            else None
        )
        rel = (
            load_reliability_model(new_ctx, list(new_ctx.iter_files()))
            if new_ctx is not None
            else None
        )
        extra = len(client_model.unknowns) if client_model is not None else 0
        extra += len(report.unknowns) if report is not None else 0
        _print_pr_summary(
            events,
            report.affected_clients if report is not None else (),
            rel,
            extra,
        )


@app.command("fingerprint")
def contract_fingerprint(
    target: Annotated[str, typer.Argument(help="Contract file or directory.")],
) -> None:
    """Print the semantic fingerprint of a contract (§180)."""
    model, name = _load_model(target)
    if model is None:
        _stderr.print(f"cannot read contract input: {target}")
        raise typer.Exit(code=2)
    typer.echo(f"{semantic_fingerprint(model)}  {name}")


@app.command()
def graph(
    target: Annotated[str, typer.Argument(help="Directory with contract + source evidence.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Show the service graph built from contract + implementation + client evidence (§161)."""
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    ctx = ProjectContext.from_root(path)
    files = list(ctx.iter_files())
    openapi = load_openapi_project(ctx)
    service_graph = contract_graph(openapi)
    try:
        scan = FastApiAdapter().scan(ctx, path.name)
    except Exception:
        scan = None
    if scan is not None:
        _merge_graph(service_graph, scan_graph(scan))
    client_model = scan_clients(ctx, files)
    _merge_graph(service_graph, client_graph(client_model))
    if json_out:
        typer.echo(json.dumps(service_graph.to_dict(), indent=2, sort_keys=True))
        return
    by_kind: dict[str, int] = {}
    for entity in service_graph.entities():
        by_kind[entity.kind] = by_kind.get(entity.kind, 0) + 1
    rel_kinds: dict[str, int] = {}
    for rel in service_graph.relationships():
        rel_kinds[str(rel.kind)] = rel_kinds.get(str(rel.kind), 0) + 1
    _console.print("entities:")
    for kind in sorted(by_kind):
        _console.print(f"  {kind}: {by_kind[kind]}")
    _console.print("relationships:")
    for kind in sorted(rel_kinds):
        _console.print(f"  {kind}: {rel_kinds[kind]}")


def _merge_graph(target_graph: ServiceGraph, other: ServiceGraph) -> None:
    for entity in other.entities():
        try:
            target_graph.add_entity(entity)
        except GraphError:
            continue
    for rel in other.relationships():
        try:
            target_graph.add_relationship(rel)
        except GraphError:
            continue


@app.command("blast-radius")
def blast_radius_cmd(
    old: Annotated[str, typer.Argument(help="Old contract file or directory.")],
    new: Annotated[str, typer.Argument(help="New contract file or directory.")],
    clients: Annotated[
        str | None, typer.Option("--clients", help="Directory of client sources.")
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """§68 blast radius: changed operation -> clients -> services -> business paths."""
    old_model, old_ctx = _load_side(old)
    new_model, _ = _load_side(new)
    if old_model is None or new_model is None:
        _stderr.print(f"cannot read contract input: {old if old_model is None else new}")
        raise typer.Exit(code=2)
    diff = diff_models(old_model, new_model)
    client_model = _load_clients(clients)
    if client_model is None:
        _stderr.print("blast radius requires --clients <dir> with client source code")
        raise typer.Exit(code=2)
    flows: tuple[SensitiveBusinessFlow, ...] = ()
    if old_ctx is not None:
        flows = load_security_model(
            old_ctx, list(old_ctx.iter_files()), openapi=old_model
        ).business_flows
    _print_blast(blast_radius(diff, old_model, client_model, flows), json_out)


def _load_executions(
    target: str,
) -> tuple[tuple[RequestExecution, ...], tuple[UnknownFact, ...]] | None:
    """Load runtime artifacts under `target` -> normalized executions."""
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read runtime artifact path: {target}")
        return None
    context = ProjectContext.from_root(path)
    files = list(context.iter_files())
    traces, _obs, unknowns = load_runtime_project(
        context, files, keep_spans=True
    )
    executions = list(executions_from_traces(traces)[0])
    summaries = _summaries(context, files)
    e2, u2 = executions_from_summaries(summaries)
    executions.extend(e2)
    unknowns = tuple(unknowns) + u2
    executions.sort(
        key=lambda e: (
            e.start_unix_nano or 0,
            e.request_id or "",
            e.trace_id or "",
            e.service or "",
            e.operation,
        )
    )
    return tuple(executions), tuple(unknowns)


def _summaries(
    context: ProjectContext, files: list[str]
) -> tuple[RequestSummary, ...]:
    out: list[RequestSummary] = []
    for f in sorted(files):
        fh = context.open_binary(f)
        if fh is None:
            continue
        with fh:
            head = fh.read(4096)
            adapter = detect_adapter(f, head)
            if adapter is None:
                continue
            fh.seek(0)
            out.extend(adapter.iter_summaries(fh, f))
    return tuple(out)


@runtime_app.command("requests")
def runtime_requests(
    target: Annotated[str, typer.Argument(help="Directory with runtime artifacts.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Summarize normalized request executions (§28, §162)."""
    loaded = _load_executions(target)
    if loaded is None:
        raise typer.Exit(code=2)
    executions, _ = loaded
    if json_out:
        typer.echo(
            json.dumps([e.to_dict() for e in executions], indent=2, sort_keys=True)
        )
        return
    table = Table(show_lines=False)
    for col in ("service", "operation", "method", "status", "ms", "downstream"):
        table.add_column(col, no_wrap=True)
    for e in executions:
        table.add_row(
            e.service or "?",
            e.operation,
            e.method or "-",
            e.status or "-",
            f"{e.duration_ms:.0f}" if e.duration_ms is not None else "-",
            str(len(e.downstream_calls)),
        )
    _console.print(table)
    _console.print(f"{len(executions)} request execution(s)")


@runtime_app.command("baseline")
def runtime_baseline(
    target: Annotated[str, typer.Argument(help="Directory with runtime artifacts.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Build runtime baselines (§36, §88, §162)."""
    loaded = _load_executions(target)
    if loaded is None:
        raise typer.Exit(code=2)
    executions, _ = loaded
    baselines = build_baselines(executions)
    if json_out:
        typer.echo(
            json.dumps([b.to_dict() for b in baselines], indent=2, sort_keys=True)
        )
        return
    table = Table(show_lines=False)
    for col in ("dim", "key", "window", "n", "p95", "err%"):
        table.add_column(col, no_wrap=True)
    for b in baselines:
        table.add_row(
            b.dimension.value,
            b.key,
            b.window,
            str(b.count),
            f"{b.latency.p95:.0f}" if b.latency else "-",
            f"{b.error_rate:.0%}" if b.error_rate is not None else "-",
        )
    _console.print(table)


@runtime_app.command("regressions")
def runtime_regressions(
    target: Annotated[str, typer.Argument(help="Directory with runtime artifacts.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Detect runtime regressions against baselines (§37, §162)."""
    loaded = _load_executions(target)
    if loaded is None:
        raise typer.Exit(code=2)
    executions, _ = loaded
    findings = run_perf_checks(executions)
    if json_out:
        typer.echo(
            json.dumps(
                export_findings(findings).to_dict(), indent=2, sort_keys=True
            )
        )
        return
    if not findings:
        _console.print("no regressions detected")
        return
    table = Table(show_lines=False)
    for col in ("id", "severity", "confidence", "detail"):
        table.add_column(col, no_wrap=(col != "detail"))
    for f in findings:
        table.add_row(f.id, f.severity.value, f.confidence.value, Text(f.description))
    _console.print(table)


@security_app.command("inspect")
def security_inspect(
    target: Annotated[str, typer.Argument(help="Project directory.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Passive security inspection (§163) - contract/config evidence only."""
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    context = ProjectContext.from_root(path)
    files = list(context.iter_files())
    openapi = load_openapi_project(context)
    try:
        scan = FastApiAdapter().scan(context, path.name)
    except Exception:
        scan = None
    model = load_security_model(context, files, openapi=openapi, routes=scan)
    findings = run_security_checks(model, openapi=openapi)
    if json_out:
        payload = {
            "model": model.to_dict(),
            "findings": export_findings(findings).to_dict(),
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    _console.print(
        f"auth schemes: {len(model.auth_schemes)} | "
        f"authz policies: {len(model.authorization)} | "
        f"drift: {len(model.auth_drift)} | "
        f"cors: {len(model.cors)} | rate limits: {len(model.rate_limits)}"
    )
    if not findings:
        _console.print("no security findings")
        return
    table = Table(show_lines=False)
    for col in ("id", "severity", "confidence", "detail"):
        table.add_column(col, no_wrap=(col != "detail"))
    for f in findings:
        table.add_row(f.id, f.severity.value, f.confidence.value, Text(f.description))
    _console.print(table)


@reliability_app.command("inspect")
def reliability_inspect(
    target: Annotated[str, typer.Argument(help="Directory with config artifacts.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Passive reliability inspection of declared config (§164)."""
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    context = ProjectContext.from_root(path)
    model = load_reliability_model(context, list(context.iter_files()))
    findings = run_reliability_checks(model)
    if json_out:
        payload = {
            "model": model.to_dict(),
            "findings": export_findings(findings).to_dict(),
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    _console.print(
        f"retry policies: {len(model.retry_policies)} | "
        f"timeouts: {len(model.timeouts)} | "
        f"circuit breakers: {len(model.circuit_breakers)} | "
        f"health checks: {len(model.health_checks)}"
    )
    if not findings:
        _console.print("no reliability findings")
        return
    table = Table(show_lines=False)
    for col in ("id", "severity", "confidence", "detail"):
        table.add_column(col, no_wrap=(col != "detail"))
    for f in findings:
        table.add_row(f.id, f.severity.value, f.confidence.value, Text(f.description))
    _console.print(table)


@reliability_app.command("path")
def reliability_path(
    target: Annotated[str, typer.Argument(help="Directory with config artifacts.")],
    hops: Annotated[
        list[str] | None,
        typer.Option("--hop", help="Hop name in call order; repeatable."),
    ] = None,
    policy: Annotated[
        list[str] | None,
        typer.Option(
            "--policy",
            help="Inline declared retry: scope=max_attempts; repeatable.",
        ),
    ] = None,
    timeout: Annotated[
        list[str] | None,
        typer.Option(
            "--timeout",
            help="Inline declared timeout: scope=ms; repeatable.",
        ),
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Reliability along an explicit call path (§164, §228)."""
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    context = ProjectContext.from_root(path)
    model = load_reliability_model(context, list(context.iter_files()))
    extra_retries = list(model.retry_policies)
    for spec in policy or []:
        scope, _, val = spec.partition("=")
        if not scope or not val.isdigit():
            _stderr.print(f"bad --policy value: {spec} (want scope=attempts)")
            raise typer.Exit(code=2)
        extra_retries.append(RetryPolicy(scope=scope, max_attempts=int(val)))
    extra_timeouts = list(model.timeouts)
    for spec in timeout or []:
        scope, _, val = spec.partition("=")
        ms = _ms_opt(val)
        if not scope or ms is None:
            _stderr.print(f"bad --timeout value: {spec} (want scope=ms)")
            raise typer.Exit(code=2)
        extra_timeouts.append(TimeoutConfig(scope=scope, timeout_ms=ms))
    scoped = ApiReliabilityModel(
        retry_policies=tuple(sorted(extra_retries, key=lambda r: r.scope)),
        timeouts=tuple(sorted(extra_timeouts, key=lambda t: t.scope)),
        circuit_breakers=model.circuit_breakers,
        load_balancing=model.load_balancing,
        health_checks=model.health_checks,
        shutdown_evidence=model.shutdown_evidence,
        idempotency=model.idempotency,
    )
    if not hops:
        _stderr.print("provide at least one --hop in call order")
        raise typer.Exit(code=2)
    findings = run_reliability_checks(scoped, hops=tuple(hops))
    if json_out:
        typer.echo(
            json.dumps(
                export_findings(findings).to_dict(), indent=2, sort_keys=True
            )
        )
        return
    if not findings:
        _console.print("no reliability findings along this path")
        return
    table = Table(show_lines=False)
    for col in ("id", "severity", "confidence", "detail"):
        table.add_column(col, no_wrap=(col != "detail"))
    for f in findings:
        table.add_row(f.id, f.severity.value, f.confidence.value, Text(f.description))
    _console.print(table)


def _ms_opt(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


@app.command()
def diagnose() -> None:
    """Cluster findings into symptoms, candidate root causes and unknowns."""
    _not_implemented("diagnose")


@app.command()
def explain(finding: Annotated[str, typer.Argument(help="Finding id to explain.")]) -> None:
    """Explain a finding."""
    _not_implemented("explain")


def main() -> None:
    app()
