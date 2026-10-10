"""Command-line interface. Command names follow §159-§166."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from forge_doctor_api import __version__
from forge_doctor_api.analyzers.clients.model import ApiClientModel
from forge_doctor_api.analyzers.clients.scan import scan_clients
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.analyzers.runtime.execution import (
    RequestExecution,
    executions_from_summaries,
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
from forge_doctor_api.diagnose import diagnose as diagnose_episodes
from forge_doctor_api.perf.baseline import build_baselines
from forge_doctor_api.reliability import (
    ApiReliabilityModel,
    RetryPolicy,
    TimeoutConfig,
    load_reliability_model,
)
from forge_doctor_api.scan import ScanReport
from forge_doctor_api.security import load_security_model
from forge_doctor_api.security.model import SensitiveBusinessFlow
from forge_doctor_api.service_graph import build_service_graph

_stderr = Console(stderr=True, highlight=False)

app = typer.Typer(
    name="forge-doctor-api",
    help="Deterministic, offline-first API architecture intelligence.",
    invoke_without_command=True,
    add_completion=False,
)
contract_app = typer.Typer(help="Inspect, diff and check API contracts.", no_args_is_help=True)
runtime_app = typer.Typer(help="Analyze exported runtime evidence.", no_args_is_help=True)
security_app = typer.Typer(help="Passive security analysis.", no_args_is_help=True)
reliability_app = typer.Typer(help="Reliability analysis.", no_args_is_help=True)

plugins_app = typer.Typer(
    help="Plugin manifests, registry and conformance.",
    no_args_is_help=True)
snapshot_app = typer.Typer(
    help="Temporal snapshots + architectural regressions.",
    no_args_is_help=True)
knowledge_app = typer.Typer(
    help="Knowledge-pack manifests, compat and precedence.",
    no_args_is_help=True)

app.add_typer(contract_app, name="contract")
app.add_typer(runtime_app, name="runtime")
app.add_typer(security_app, name="security")
app.add_typer(reliability_app, name="reliability")
app.add_typer(plugins_app, name="plugins")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(knowledge_app, name="knowledge")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"forge-doctor-api {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Deterministic, offline-first API architecture intelligence."""
    if ctx.invoked_subcommand is None:
        import sys as _sys

        if _sys.stdin.isatty() and _sys.stdout.isatty():
            try:
                from forge_doctor_api.ui.home import run_home
                from forge_doctor_api.ui.kit import NonInteractive

                try:
                    raise typer.Exit(run_home())
                except NonInteractive:
                    pass
            except ImportError:
                pass
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def scan(
    target: Annotated[str, typer.Argument(help="Project directory.")] = ".",
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            help="§178 gate categories, comma-separated: breaking,security,policy.",
        ),
    ] = None,
    baseline: Annotated[
        str | None,
        typer.Option("--baseline", help="Baseline contract file/dir for the breaking gate."),
    ] = None,
    policy: Annotated[
        str | None,
        typer.Option("--policy", help="Extra policy file/dir merged into evaluation."),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            help="console | json | jsonl | sarif | agent | report (full DoctorReport)."),
    ] = "console",
    out: Annotated[
        str | None, typer.Option("--out", help="Write the export to a file.")
    ] = None,
    stats_timing: Annotated[
        bool,
        typer.Option(
            "--stats-timing",
            help="Record per-analyzer wall time in report.stats "
            "(non-canonical; excluded from deterministic hashing)."),
    ] = False,
    incremental: Annotated[
        bool,
        typer.Option(
            "--incremental",
            help="Reuse cached analyzer models under "
            ".forge-doctor/cache/ (findings always recompute)."),
    ] = False,
) -> None:
    """§177 full scan: every deterministic pipeline + optional §178 gate."""
    from forge_doctor_api.output.writers import (
        write_agent,
        write_jsonl,
        write_sarif,
    )
    from forge_doctor_api.scan import (
        GateCategory,
        _GateConfigError,
        evaluate_gate,
        export_scan,
        scan_project,
    )

    categories: set[GateCategory] = set()
    for part in (fail_on or "").split(","):
        part = part.strip().lower()
        if not part:
            continue
        try:
            categories.add(GateCategory(part))
        except ValueError:
            _stderr.print(
                f"unknown fail-on category: {part} "
                "(expected breaking|security|policy)")
            raise typer.Exit(code=2) from None

    ctx = ProjectContext(root=Path(target).resolve())
    before = ProjectContext(root=Path(baseline).resolve()) if baseline else None
    extra_policy = (
        ProjectContext(root=Path(policy).resolve()) if policy else None)
    report = scan_project(ctx, before=before, extra_policy=extra_policy,
                          stats_timing=stats_timing,
                          incremental=incremental)
    try:
        failures = evaluate_gate(report.findings, report.diff,
                                 frozenset(categories))
    except _GateConfigError as exc:
        _stderr.print(str(exc))
        raise typer.Exit(code=2) from None
    import dataclasses
    report = dataclasses.replace(report, gate_failures=failures)

    if fmt == "console":
        _print_scan_console(report)
    elif fmt == "report":
        _emit_text(report.to_json(), out)
    elif fmt == "json":
        payload = export_scan(report)
        payload["findings"] = [f.to_dict() for f in report.findings]
        payload["unknowns"] = [u.to_dict() for u in report.unknowns]
        _emit_text(json.dumps(payload, indent=2), out)
    elif fmt == "jsonl":
        _emit_text(write_jsonl(report.findings), out)
    elif fmt == "sarif":
        _emit_text(write_sarif(report.findings), out)
    elif fmt == "agent":
        _emit_text(write_agent(report.findings, report.unknowns), out)
    else:
        _stderr.print(f"unknown format: {fmt} "
                      "(expected console|json|jsonl|sarif|agent|report)")
        raise typer.Exit(code=2)

    if failures:
        raise typer.Exit(code=1)


def _emit_text(text: str, out: str | None) -> None:
    if out:
        Path(out).write_text(text + ("\n" if text else ""), encoding="utf-8")
    else:
        typer.echo(text)


def _print_scan_console(report: ScanReport) -> None:
    table = Table("id", "severity", "confidence", "subject", "description")
    for f in report.findings:
        subject = f.entity_ids[0] if f.entity_ids else (
            f.source_location.path if f.source_location else "-")
        table.add_row(
            f.id, f.severity.value, f.confidence.value, subject,
            f.description[:80])
    _console.print(table)
    if report.unknowns:
        _console.print(f"[dim]Unknowns: {len(report.unknowns)}[/dim]")
    for failure in report.gate_failures:
        _console.print(
            f"[red]GATE {failure.category}[/red] {failure.detail}")
    status = "[green]PASS[/green]" if report.gate_passed else "[red]FAIL[/red]"
    _console.print(f"gate: {status}")





@app.command()
def inventory(
    target: Annotated[str, typer.Argument(help="Workspace or repo directory.")] = ".",
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """§159 inventory: services, APIs, operations, protocols, owners."""
    from forge_doctor_api.fleet import build_fleet_report
    from forge_doctor_api.workspace import (
        MemberRole,
        Workspace,
        WorkspaceMember,
        load_workspace,
    )

    root = Path(target).resolve()
    if not root.is_dir():
        _stderr.print(f"inventory: not a directory: {target}")
        raise typer.Exit(code=2)
    ctx = ProjectContext.from_root(root)
    workspace = load_workspace(ctx) or Workspace(
        name=root.name,
        members=(WorkspaceMember(
            name=root.name, path=".", role=MemberRole.MIXED,
        ),),
    )
    report = build_fleet_report(ctx, workspace)
    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return

    _console.print(f"Workspace: {report.workspace}")
    if report.members_missing:
        _console.print(
            f"  missing members: {', '.join(report.members_missing)} [UNKNOWN]"
        )
    table = Table("repo", "role", "styles", "apis", "ops", "gw", "ext", "owner")
    for m in report.portfolio:
        table.add_row(
            m.repo, m.role, ",".join(m.styles) or "-", str(m.apis),
            str(m.operations), str(m.gateways), str(m.external_apis),
            m.owner or "unknown",
        )
    _console.print(table)
    for q in report.questions:
        _console.print(f"[bold]{q.question}[/bold]")
        for e in q.entries:
            _console.print(f"  {e.repo}: {e.detail}")
        for u in q.unknowns:
            _console.print(f"  [UNKNOWN] {u.missing}")
    if report.complexity:
        _console.print("[bold]Complexity signals (opportunities)[/bold]")
        for s in report.complexity:
            _console.print(f"  {s.kind}: {s.detail}")
    if report.deprecations:
        _console.print("[bold]Deprecation readiness[/bold]")
        for dep in report.deprecations:
            clients = (
                "unknown" if dep.remaining_clients is None
                else str(dep.remaining_clients)
            )
            _console.print(
                f"  {dep.repo}: clients={clients} "
                f"traffic={'unknown' if dep.observed_traffic is None else dep.observed_traffic} "
                f"replacement={dep.replacement or 'none'} "
                f"age={dep.contract_age_days if dep.contract_age_days is not None else 'unknown'}d"
            )


@app.command()
def lab(
    target: Annotated[str, typer.Argument(help="Labs corpus directory.")] = "labs",
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
    no_record: Annotated[
        bool, typer.Option("--no-record", help="Skip factory/runs record.")
    ] = False,
) -> None:
    """§199-§201 Forge Lab: run every scenario + report per-family precision."""
    from forge_doctor_api.core.context import system_clock
    from forge_doctor_api.lab import run_labs, write_run_record

    root = Path(target).resolve()
    if not root.is_dir():
        _stderr.print(f"lab: not a directory: {target}")
        raise typer.Exit(code=2)
    ctx = ProjectContext.from_root(root, clock=system_clock())
    report = run_labs(ctx)
    if not no_record:
        stamp = ctx.now().strftime("%Y%m%dT%H%M%SZ")
        record = write_run_record(report, root.parent / "factory" / "runs", stamp)
        _stderr.print(f"lab: run record -> {record}")
    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        raise typer.Exit(code=0 if report.failed == 0 else 1)

    _console.print(
        f"Forge Lab: {report.passed} passed, {report.failed} failed, "
        f"{report.skipped} skipped"
    )
    if report.extras_absent:
        _console.print(
            f"  install profile: extras absent: "
            f"{', '.join(report.extras_absent)}"
        )
    for r in report.results:
        if r.skipped:
            _console.print(
                f"  [yellow]SKIP[/yellow] {r.domain}/{r.name} "
                f"({r.skip_reason})"
            )
            continue
        mark = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        _console.print(f"  {mark} {r.domain}/{r.name}")
        if not r.passed:
            for label, values in (
                ("missing findings", r.missing_findings),
                ("unexpected findings", r.unexpected_findings),
                ("forbidden hits", r.forbidden_hits),
                ("missing entities", r.missing_entities),
                ("forbidden entities", r.forbidden_entity_hits),
                ("missing clients", r.missing_clients),
                ("missing breaking", r.missing_breaking),
                ("missing signals", r.missing_runtime_signals),
                ("missing issues", r.missing_issues),
                ("wording", r.wording_violations),
                ("problems", r.problems),
            ):
                for v in values:
                    _console.print(f"      {label}: {v}")
    if report.families:
        _console.print("[bold]Per-family metrics[/bold]")
        table = Table(
            "family", "tp", "fp", "fn", "precision", "recall",
            "unknown", "unsupp", "parse", "ms", "peak-KB", "n", "conf",
        )
        for f in report.families:
            table.add_row(
                f.family, str(f.tp), str(f.fp), str(f.fn),
                "-" if f.precision is None else f"{f.precision:.2f}",
                "-" if f.recall is None else f"{f.recall:.2f}",
                "-" if f.unknown_rate is None else f"{f.unknown_rate:.2f}",
                "-" if f.unsupported_rate is None
                else f"{f.unsupported_rate:.2f}",
                str(f.parse_failures), str(f.elapsed_ms),
                str(f.peak_bytes // 1024), str(f.sample_size),
                f.coverage_confidence,
            )
        _console.print(table)
    if report.domains:
        _console.print("[bold]Per-domain metrics[/bold]")
        table = Table(
            "domain", "scenarios", "tp", "fp", "fn",
            "precision", "recall", "unknowns", "parse", "ms",
        )
        for d in report.domains:
            table.add_row(
                d.domain, str(d.scenarios), str(d.tp), str(d.fp),
                str(d.fn),
                "-" if d.precision is None else f"{d.precision:.2f}",
                "-" if d.recall is None else f"{d.recall:.2f}",
                str(d.unknowns), str(d.parse_failures), str(d.elapsed_ms),
            )
        _console.print(table)
    raise typer.Exit(code=0 if report.failed == 0 else 1)


@contract_app.command("inspect")
def contract_inspect(
    target: Annotated[str, typer.Argument(help="Contract file or directory.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Inspect an API contract: documents, operations, schemas, servers, refs.

    Metadata surface only — never emits schema bodies or payloads.
    """
    model, name = _load_model(target)
    if model is None or not model.documents:
        _stderr.print(f"cannot read contract input: {target}")
        raise typer.Exit(code=2)
    schemas = sorted({s.name for s in model.schemas})
    servers = sorted({s.url for s in model.servers})
    schemes = sorted({s.name for s in model.security_schemes})
    payload: dict[str, Any] = {
        "target": name,
        "documents": [
            {
                "path": d.location.path,
                "format": d.format,
                "status": d.status.value,
                "openapi_version": d.openapi_version,
                "version_family": d.version_family,
                "title": d.title,
                "api_version": d.api_version,
            }
            for d in model.documents
        ],
        "operations": [
            {
                "method": op.method,
                "path": op.path,
                "operation_id": op.operation_id,
                "deprecated": op.deprecated,
            }
            for op in model.operations
        ],
        "schemas": schemas,
        "servers": servers,
        "security_schemes": schemes,
        "unresolved_external_refs": [
            {"ref": r.ref, "path": r.location.path, "reason": r.reason.value}
            for r in model.unresolved_external_refs
        ],
        "issues": [
            {"code": i.code.value, "message": i.message, "path": i.location.path}
            for i in model.issues
        ],
        "summary": {
            "documents": len(model.documents),
            "operations": len(model.operations),
            "schemas": len(model.schemas),
            "unresolved_external_refs": len(model.unresolved_external_refs),
            "issues": len(model.issues),
        },
    }
    if json_out:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    for d in model.documents:
        _console.print(
            f"{d.location.path}  [{d.format}]  {d.status.value}  "
            f"openapi={d.openapi_version or 'unknown'}  "
            f"{d.title or 'untitled'} {d.api_version or ''}".rstrip()
        )
    _console.print(f"operations: {len(model.operations)}")
    table = Table("method", "path", "operation_id", "deprecated")
    for op in model.operations:
        table.add_row(
            op.method, op.path, op.operation_id or "-",
            "yes" if op.deprecated else "",
        )
    _console.print(table)
    if schemas:
        _console.print(f"schemas ({len(schemas)}): " + ", ".join(schemas))
    if servers:
        _console.print("servers: " + ", ".join(servers))
    if schemes:
        _console.print("security schemes: " + ", ".join(schemes))
    for ref in model.unresolved_external_refs:
        _console.print(
            f"[yellow]unresolved ref[/yellow] {ref.ref} "
            f"({ref.location.path}) — {ref.reason.value}")
    for issue in model.issues:
        _console.print(f"[yellow]issue[/yellow] {issue.code.value}: "
                       f"{issue.message} ({issue.location.path})")


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
    view: Annotated[
        bool, typer.Option("--view", help="Emit ForgeGraphView/v1 (Graph Studio contract).")
    ] = False,
    ui: Annotated[
        bool, typer.Option("--ui", help="Open the local Graph Studio explorer.")
    ] = False,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Serve without opening a browser (SSH).")
    ] = False,
    port: Annotated[int, typer.Option("--port", help="Port to bind (default ephemeral).")] = 0,
) -> None:
    """Show the service graph built from contract + implementation + client evidence (§161)."""
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    if view or ui:
        from forge_doctor_api.graphview import build_view

        gv = build_view(path)
        if gv is None:
            _stderr.print("no service graph could be built for this target")
            raise typer.Exit(code=2)
        if ui:
            from forge_doctor_api._graphstudio import (
                graph_studio_enabled,
                open_studio,
            )

            if not graph_studio_enabled(
                path,
                state_rel=".forge-doctor-api/install",
                user_state_rel="~/.forge-doctor-api/install",
            ):
                _stderr.print(
                    "Graph Studio declined at install — reinstall with graph-studio"
                )
                raise typer.Exit(code=2)
            raise typer.Exit(
                open_studio([gv], open_browser=not no_browser, port=port)
            )
        typer.echo(json.dumps(gv.to_dict(), indent=2, sort_keys=True))
        return
    service_graph = build_service_graph(path)
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
    rt = load_runtime_project(context, files, keep_spans=False)
    unknowns = rt.unknowns
    executions = list(rt.executions)
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
def diagnose(
    target: Annotated[str, typer.Argument(
        help="Directory with current-state evidence (contract + config + runtime artifacts).",
    )],
    before: Annotated[
        str | None, typer.Option("--before", help="Prior-state directory for the change diff.")
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """§165 cluster findings into symptom/candidate causes/affected services/unknowns."""
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    loaded = _load_executions(target)
    executions: tuple[RequestExecution, ...] = ()
    load_unknowns: tuple[UnknownFact, ...] = ()
    if loaded is not None:
        executions, load_unknowns = loaded
    ctx = ProjectContext.from_root(path)
    reliability = load_reliability_model(ctx, list(ctx.iter_files()))

    events: tuple[ChangeEvent, ...] = ()
    if before is not None:
        old_model, old_ctx = _load_side(before)
        new_model, _ = _load_side(target)
        if old_model is not None and new_model is not None:
            diff = diff_models(old_model, new_model)
            events = change_report(
                diff, _config_events_for(old_model, new_model, old_ctx, ctx)
            ).events

    findings = run_perf_checks(executions)
    report = diagnose_episodes(executions, findings, events, reliability)
    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return
    if not report.episodes:
        _console.print("no incident episodes")
        for u in (*report.unknowns, *load_unknowns):
            _console.print(f"UNKNOWN: {u.subject} — {u.missing}")
        return
    for ep in report.episodes:
        _console.print(f"Symptom:\n  {ep.symptom}")
        if ep.path:
            _console.print("Path:")
            for hop in ep.path:
                _console.print(f"  -> {hop.service} [{hop.signal.value}] {hop.detail}")
        if ep.changes:
            _console.print("Change:")
            for change in ep.changes:
                _console.print(f"  {change}")
        if ep.observed:
            _console.print("Observed:")
            for obs in ep.observed:
                _console.print(f"  {obs.detail}")
        _console.print("Candidate cause:")
        if not ep.candidates:
            _console.print("  (none evidenced)")
        for c in ep.candidates:
            _console.print(
                f"  [{c.rank}] {c.tier.value} {c.subject} ({c.kind}) — {c.rationale}"
            )
        _console.print(f"  affected services: {', '.join(ep.affected_services)}")
        if ep.slo:
            _console.print(f"  slo objectives: {', '.join(ep.slo)}")
    all_unknowns = (*report.unknowns, *load_unknowns)
    if all_unknowns:
        _console.print("Unknowns:")
        for u in all_unknowns:
            _console.print(f"  {u.subject}: {u.missing}")


@app.command()
def explain(
    target: Annotated[str, typer.Argument(help="Directory the finding came from.")],
    finding: Annotated[str, typer.Argument(help="Finding id or subject token to explain.")],
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """§166 render the evidence chain + rule rationale for a finding."""
    from forge_doctor_api.core.stats import describe_check, rule_text
    from forge_doctor_api.scan import scan_project

    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    ctx = ProjectContext.from_root(path)
    findings = scan_project(ctx).findings
    token = finding.lower()
    matches = [
        f for f in findings
        if token in f.id.lower() or token in f.description.lower()
        or any(token in e.lower() for e in f.entity_ids)
    ]
    if not matches:
        _stderr.print(f"no finding matching: {finding}")
        raise typer.Exit(code=2)
    if len(matches) > 1:
        _console.print(f"{len(matches)} findings match — disambiguate:")
        for f in matches:
            _console.print(f"  {f.id}  {Text(f.description).plain[:80]}")
        raise typer.Exit(code=2)
    f = matches[0]
    rule = describe_check(f.id)
    if json_out:
        typer.echo(json.dumps(f.to_dict(), indent=2, sort_keys=True))
        return
    _console.print(f"{f.id}  [{f.severity.value}] [{f.confidence.value}]")
    _console.print(Text(f.description).plain)
    if rule is not None:
        _console.print(f"rule: {rule.title} — {Text(rule_text(rule)).plain}")
    _console.print(f"evidence kind: {f.evidence_kind.value}")
    for ev in f.evidence:
        loc = f"{ev.source}:{ev.line}" if ev.line else ev.source
        _console.print(f"  {ev.kind.value}  {loc}  — {Text(ev.summary).plain}")
    if f.source_location:
        _console.print(f"source: {f.source_location.path}:{f.source_location.line or ''}")
    for u in f.unknowns:
        _console.print(f"UNKNOWN: {u.subject} — {u.missing} ({u.resolution})")
    next_evidence = [u.resolution for u in f.unknowns if u.resolution]
    if next_evidence:
        _console.print("next evidence:")
        for suggestion in next_evidence:
            _console.print(f"  - {suggestion}")
    if f.remediation:
        _console.print(f"remediation: {Text(f.remediation).plain}")


@app.command()
def mcp(
    target: Annotated[str, typer.Argument(
        help="Project directory to serve over MCP.",
    )] = ".",
    transport: Annotated[str, typer.Option(
        "--transport", help="stdio (default).",
    )] = "stdio",
) -> None:
    """§216 serve the Doctor over MCP (requires the `mcp` extra)."""
    if transport != "stdio":
        _stderr.print(f"unknown transport: {transport} (expected stdio)")
        raise typer.Exit(code=2)
    path = Path(target).resolve()
    if not path.is_dir():
        _stderr.print(f"cannot read path: {target}")
        raise typer.Exit(code=2)
    try:
        from forge_doctor_api.handoff.mcp_server import (
            McpDependencyError,
            serve_stdio,
        )
        serve_stdio(path)
    except McpDependencyError as exc:
        _stderr.print(str(exc))
        raise typer.Exit(code=2) from None


@plugins_app.command("list")
def plugins_list(
    directory: Annotated[str, typer.Option(
        "--dir", help="Directory scanned for plugin manifests.",
    )] = "plugins",
) -> None:
    """§52 list discovered plugin manifests + rejection reasons."""
    from forge_doctor_api.plugins.registry import discover_registry

    registry = discover_registry(Path(directory))
    table = Table("id", "version", "trust", "compat", "capabilities")
    for m in registry.list():
        table.add_row(
            m.plugin_id, m.version, m.trust.value,
            "yes" if registry.compatible(m) else "no",
            ",".join(m.capabilities) or "-")
    _console.print(table)
    for r in registry.rejections:
        _stderr.print(f"rejected {r.path}: {r.reason}")
    for c in registry.conflicts():
        _stderr.print(f"conflict {c.kind}: {c.detail}")


@plugins_app.command("inspect")
def plugins_inspect(
    plugin_id: Annotated[str, typer.Argument(help="Plugin id.")],
    directory: Annotated[str, typer.Option(
        "--dir", help="Directory scanned for plugin manifests.",
    )] = "plugins",
) -> None:
    """§52 manifest + compat + rejection reasons for one plugin."""
    from forge_doctor_api.plugins.registry import discover_registry

    registry = discover_registry(Path(directory))
    manifest = registry.get(plugin_id)
    if manifest is None:
        related = [r for r in registry.rejections
                   if plugin_id in r.path]
        for r in related:
            _stderr.print(f"{r.path}: {r.reason}")
        _stderr.print(f"unknown plugin: {plugin_id}")
        raise typer.Exit(code=2)
    _console.print(manifest.to_json())


@plugins_app.command("verify")
def plugins_verify(
    plugin_id: Annotated[str, typer.Argument(help="Plugin id.")],
    target: Annotated[str, typer.Argument(
        help="Project the plugin analyzes during conformance.",
    )] = ".",
    directory: Annotated[str, typer.Option(
        "--dir", help="Directory scanned for plugin manifests.",
    )] = "plugins",
) -> None:
    """§54 compat check + conformance preflight (never imports UNTRUSTED)."""
    from forge_doctor_api.plugins.conformance import (
        plugin_run_surface,
        run_conformance,
    )
    from forge_doctor_api.plugins.registry import discover_registry

    registry = discover_registry(Path(directory))
    manifest = registry.get(plugin_id)
    if manifest is None:
        _stderr.print(f"unknown plugin: {plugin_id}")
        raise typer.Exit(code=2)
    if not registry.compatible(manifest):
        _stderr.print(
            f"incompatible: requires {manifest.doctor_api!r}")
        raise typer.Exit(code=1)
    try:
        module = registry.activate(plugin_id)
    except Exception as exc:
        _stderr.print(f"activation refused: {exc}")
        raise typer.Exit(code=2) from None
    run = plugin_run_surface(module)
    if run is None:
        _stderr.print("plugin exposes no analyze/adapter surface")
        raise typer.Exit(code=2)
    report = run_conformance(plugin_id, run, Path(target).resolve())
    table = Table("check", "status", "details")
    for c in report.checks:
        table.add_row(c.name, c.status, c.details)
    _console.print(table)
    raise typer.Exit(code=0 if report.passed else 1)


# -- snapshot (spec 059) ------------------------------------------------------


def _store(target: str) -> Any:
    from forge_doctor_api.temporal import SNAPSHOT_DIR, SnapshotStore
    return SnapshotStore(Path(target).resolve() / SNAPSHOT_DIR)


@snapshot_app.command("save")
def snapshot_save(
    target: Annotated[str, typer.Argument(help="Project directory.")] = ".",
    label: Annotated[str, typer.Option("--label")] = "",
) -> None:
    """Scan the project and store a snapshot under .forge-doctor/."""
    from forge_doctor_api.core.context import system_clock
    from forge_doctor_api.scan import scan_project
    ctx = ProjectContext(root=Path(target).resolve(),
                         clock=system_clock())
    snap = _store(target).save(
        scan_project(ctx), label=label, created_at=ctx.now())
    _console.print(
        f"snapshot {snap.id} label={snap.label} rev={snap.hash[:12]}")


@snapshot_app.command("list")
def snapshot_list(
    target: Annotated[str, typer.Argument()] = ".",
) -> None:
    """List stored snapshots (never creates the store)."""
    table = Table("id", "label", "created_at")
    for s in _store(target).list():
        table.add_row(s.id, s.label, s.created_at)
    _console.print(table)


def _pair(target: str, a: str, b: str) -> tuple[Any, Any]:
    from forge_doctor_api.temporal import SnapshotError
    store = _store(target)
    try:
        return store.report(a), store.report(b)
    except SnapshotError as exc:
        _stderr.print(str(exc))
        raise typer.Exit(code=2) from None


@snapshot_app.command("diff")
def snapshot_diff(
    a: Annotated[str, typer.Argument(help="Snapshot id/label (older).")],
    b: Annotated[str, typer.Argument(help="Snapshot id/label (newer).")],
    target: Annotated[str, typer.Option("--target")] = ".",
) -> None:
    """Delta context between two snapshots (spec-049 delta)."""
    from forge_doctor_api.handoff.delta import compute_delta
    prev, cur = _pair(target, a, b)
    delta = compute_delta(prev, cur)
    _console.print(delta.to_json())


@snapshot_app.command("regressions")
def snapshot_regressions(
    a: Annotated[str, typer.Argument(help="Snapshot id/label (older).")],
    b: Annotated[str, typer.Argument(help="Snapshot id/label (newer).")],
    target: Annotated[str, typer.Option("--target")] = ".",
) -> None:
    """Evidence-backed architectural regressions a -> b."""
    from forge_doctor_api.temporal import architectural_regressions
    prev, cur = _pair(target, a, b)
    findings = architectural_regressions(
        prev, cur,
        prev_ref=f"doctor://report/{a}", cur_ref=f"doctor://report/{b}")
    table = Table("id", "severity", "title")
    for f in findings:
        table.add_row(f.id, f.severity.value, f.title)
    _console.print(table)
    raise typer.Exit(code=1 if findings else 0)


# -- knowledge (spec 064) -----------------------------------------------------


@knowledge_app.command("list")
def knowledge_list(
    dirs: Annotated[list[str], typer.Argument(
        help="Pack dirs, highest precedence first.")] = [],  # noqa: B006
    target: Annotated[str, typer.Option(
        "--target", help="Project dir for .forge-doctor/knowledge.")] = ".",
) -> None:
    """List pack manifests with lifecycle status.

    Precedence: explicit dirs > project .forge-doctor/knowledge > builtin.
    """
    from forge_doctor_api.knowledge.manifest import (
        PROJECT_PACK_DIR,
        list_packs,
    )
    ordered = [Path(d).resolve() for d in dirs]
    project_pack = Path(target).resolve() / PROJECT_PACK_DIR
    if project_pack.is_dir():
        ordered.append(project_pack)
    listings, unknowns = list_packs(tuple(ordered))
    table = Table("id", "version", "source", "status", "details")
    for li in listings:
        m = li.manifest
        table.add_row(
            m.id if m else "-", m.version if m else "-",
            li.source, li.status.value, li.details)
    _console.print(table)
    for u in unknowns:
        _stderr.print(f"unknown: {u.subject} - {u.missing}")


@knowledge_app.command("validate")
def knowledge_validate(
    directory: Annotated[str, typer.Argument(help="Pack dir or toml file.")],
) -> None:
    """Strict-validate one knowledge manifest."""
    from forge_doctor_api.knowledge.manifest import compatible, load_manifest
    manifest, errors = load_manifest(Path(directory).resolve())
    for e in errors:
        _stderr.print(f"error: {e}")
    if manifest is None:
        raise typer.Exit(code=2)
    ok, reason = compatible(manifest)
    if not ok:
        _stderr.print(f"incompatible: {reason}")
        raise typer.Exit(code=1)
    _console.print(
        f"{manifest.id} {manifest.version} compat=ok "
        f"provides={list(manifest.provides)}")


def main() -> None:
    import sys

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    app()
