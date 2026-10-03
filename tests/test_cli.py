from __future__ import annotations

import pytest
from typer.testing import CliRunner

from forge_doctor_api import __version__
from forge_doctor_api.cli import NOT_IMPLEMENTED_EXIT_CODE, app

runner = CliRunner()

PLACEHOLDERS = [
    ["scan"],
    ["inventory"],
    ["contract", "inspect"],
    ["diagnose"],
    ["explain", "OAS001"],
]


@pytest.mark.parametrize("args", PLACEHOLDERS, ids=" ".join)
def test_placeholder_commands_report_not_implemented(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == NOT_IMPLEMENTED_EXIT_CODE
    assert "not implemented" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"forge-doctor-api {__version__}"


def test_help_lists_command_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("scan", "inventory", "contract", "graph", "runtime", "security", "diagnose"):
        assert name in result.output


def test_explain_requires_finding() -> None:
    result = runner.invoke(app, ["explain"])
    assert result.exit_code == 2
