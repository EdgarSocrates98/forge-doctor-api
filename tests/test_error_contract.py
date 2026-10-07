"""Spec 030 — §147 org standard-error-contract evaluation."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.checks.drift.error_contract import (
    RFC7807,
    ErrorConformance,
    evaluate_error_contract,
)
from forge_doctor_api.core.context import ProjectContext

_CONFORMS = """\
openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /items:
    get:
      operationId: listItems
      responses:
        "200": {description: ok}
        "404":
          description: not found
          content:
            application/problem+json:
              schema:
                type: object
                properties:
                  type: {type: string}
                  title: {type: string}
                  status: {type: integer}
"""

_VIOLATES = """\
openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /items:
    get:
      operationId: listItems
      responses:
        "200": {description: ok}
        "404":
          description: not found
          content:
            application/json:
              schema:
                type: object
                properties:
                  message: {type: string}
"""

_NO_ERRORS = """\
openapi: "3.0.3"
info: {title: T, version: "1.0"}
paths:
  /items:
    get:
      operationId: listItems
      responses:
        "200": {description: ok}
"""


def _eval(text: str, tmp_path: Path):
    (tmp_path / "openapi.yaml").write_text(text, encoding="utf-8")
    model = load_openapi_project(ProjectContext.from_root(tmp_path))
    return evaluate_error_contract(model, RFC7807)


def test_conforms(tmp_path: Path) -> None:
    report = _eval(_CONFORMS, tmp_path)
    assert report.contract == "rfc7807-problem-json"
    assert report.verdicts[0].status is ErrorConformance.CONFORMS
    assert report.verdicts[0].evidence


def test_violation_details(tmp_path: Path) -> None:
    report = _eval(_VIOLATES, tmp_path)
    v = report.verdicts[0]
    assert v.status is ErrorConformance.VIOLATION
    assert "application/problem+json" in v.detail
    assert "type" in v.detail and "title" in v.detail


def test_no_error_surface_is_unknown(tmp_path: Path) -> None:
    report = _eval(_NO_ERRORS, tmp_path)
    assert report.verdicts[0].status is ErrorConformance.UNKNOWN


def test_custom_contract(tmp_path: Path) -> None:
    from forge_doctor_api.checks.drift.error_contract import ErrorContract
    contract = ErrorContract(
        name="org-json-error",
        required_content_types=("application/json",),
        required_fields=("message",),
    )
    (tmp_path / "openapi.yaml").write_text(_VIOLATES, encoding="utf-8")
    model = load_openapi_project(ProjectContext.from_root(tmp_path))
    report = evaluate_error_contract(model, contract)
    assert report.verdicts[0].status is ErrorConformance.CONFORMS
