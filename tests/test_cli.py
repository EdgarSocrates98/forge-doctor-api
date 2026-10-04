from __future__ import annotations

import json

from typer.testing import CliRunner

from forge_doctor_api import __version__
from forge_doctor_api.cli import app

runner = CliRunner()

_CONTRACT = """\
openapi: 3.0.3
info:
  title: Orders API
  version: 1.2.3
servers:
  - url: https://api.example.com
paths:
  /orders:
    get:
      operationId: listOrders
      responses:
        '200':
          description: ok
components:
  schemas:
    Order:
      type: object
"""


def test_contract_inspect_console(tmp_path) -> None:
    (tmp_path / "openapi.yaml").write_text(_CONTRACT)
    result = runner.invoke(app, ["contract", "inspect", str(tmp_path)])
    assert result.exit_code == 0
    assert "Orders API" in result.output
    assert "listOrders" in result.output
    assert "GET" in result.output


def test_contract_inspect_json(tmp_path) -> None:
    (tmp_path / "openapi.yaml").write_text(_CONTRACT)
    result = runner.invoke(
        app, ["contract", "inspect", str(tmp_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["operations"] == 1
    assert payload["operations"][0]["operation_id"] == "listOrders"
    assert payload["schemas"] == ["Order"]
    assert payload["servers"] == ["https://api.example.com"]
    assert payload["documents"][0]["title"] == "Orders API"


def test_contract_inspect_never_emits_schema_bodies(tmp_path) -> None:
    (tmp_path / "openapi.yaml").write_text(_CONTRACT)
    result = runner.invoke(
        app, ["contract", "inspect", str(tmp_path), "--json"])
    assert "type" not in json.dumps(result.output)
    assert "properties" not in result.output


def test_contract_inspect_missing_target_exits_2(tmp_path) -> None:
    result = runner.invoke(
        app, ["contract", "inspect", str(tmp_path / "nope")])
    assert result.exit_code == 2


def test_contract_inspect_dir_without_contract_exits_2(tmp_path) -> None:
    result = runner.invoke(app, ["contract", "inspect", str(tmp_path)])
    assert result.exit_code == 2


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
