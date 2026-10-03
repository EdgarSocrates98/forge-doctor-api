"""Command-line interface. Command names follow §159-§166."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from forge_doctor_api import __version__
from forge_doctor_api.analyzers.openapi.model import OpenApiProjectModel
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.compat import ContractDiff, diff_models, semantic_fingerprint
from forge_doctor_api.checks.compat.catalog import CompatibilityClass
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.export import export_findings

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
        bool, typer.Option("--semantic", help="Emit the semantic change list.")
    ] = True,
    json_out: Annotated[bool, typer.Option("--json", help="JSON output.")] = False,
) -> None:
    """Semantic contract diff (§66)."""
    diff = _diff_report(old, new)
    if diff is None:
        raise typer.Exit(code=2)
    _print_diff(diff, json_out)


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
def graph() -> None:
    """Show the service graph."""
    _not_implemented("graph")


@app.command("blast-radius")
def blast_radius() -> None:
    """Show the blast radius of a change."""
    _not_implemented("blast-radius")


@runtime_app.command("requests")
def runtime_requests() -> None:
    """Summarize request evidence."""
    _not_implemented("runtime requests")


@runtime_app.command("baseline")
def runtime_baseline() -> None:
    """Build runtime baselines."""
    _not_implemented("runtime baseline")


@runtime_app.command("regressions")
def runtime_regressions() -> None:
    """Detect runtime regressions against baselines."""
    _not_implemented("runtime regressions")


@security_app.command("inspect")
def security_inspect() -> None:
    """Passive security inspection."""
    _not_implemented("security inspect")


@reliability_app.command("inspect")
def reliability_inspect() -> None:
    """Inspect reliability configuration."""
    _not_implemented("reliability inspect")


@reliability_app.command("path")
def reliability_path() -> None:
    """Analyze reliability along a request path."""
    _not_implemented("reliability path")


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
