"""Command-line interface. Command names follow §159-§166."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from forge_doctor_api import __version__

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


@contract_app.command("diff")
def contract_diff() -> None:
    """Diff two API contracts."""
    _not_implemented("contract diff")


@contract_app.command("compatibility")
def contract_compatibility() -> None:
    """Classify contract changes by compatibility."""
    _not_implemented("contract compatibility")


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
