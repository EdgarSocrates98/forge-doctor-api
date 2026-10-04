"""Spec 049 — DeltaContext: prev/current report diff."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.handoff.delta import compute_delta
from forge_doctor_api.scan import scan_project

OPENAPI_V1 = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""

OPENAPI_V2 = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
  /dogs:
    get:
      operationId: listDogs
      responses: {"200": {description: ok}}
"""


def _report(tmp_path: Path, doc: str):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "api.yaml").write_text(doc, encoding="utf-8")
    return scan_project(ProjectContext.from_root(tmp_path))


def test_initial_delta(tmp_path: Path) -> None:
    cur = _report(tmp_path, OPENAPI_V1)
    delta = compute_delta(None, cur)
    assert delta.initial
    assert delta.analysis_rev_cur == cur.analysis_rev
    assert "contracts" in delta.domains_added


def test_identical_reports_empty_delta(tmp_path: Path) -> None:
    a = _report(tmp_path, OPENAPI_V1)
    b = _report(tmp_path, OPENAPI_V1)
    delta = compute_delta(a, b)
    assert not delta.initial
    assert delta.empty


def test_changed_contract_produces_delta(tmp_path: Path) -> None:
    a = _report(tmp_path / "a", OPENAPI_V1)
    b = _report(tmp_path / "b", OPENAPI_V2)
    delta = compute_delta(a, b)
    assert not delta.empty
    assert delta.operations_added == ("operation_id:listDogs",)


def test_changed_operation_digest(tmp_path: Path) -> None:
    v2_changed = OPENAPI_V1.replace(
        "operationId: listPets",
        "operationId: listPets\n      deprecated: true")
    a = _report(tmp_path / "a", OPENAPI_V1)
    b = _report(tmp_path / "b", v2_changed)
    delta = compute_delta(a, b)
    assert delta.operations_changed == ("operation_id:listPets",)
    assert not delta.operations_added


def test_finding_add_remove(tmp_path: Path) -> None:
    from forge_doctor_api.core.models import (
        EvidenceKind,
        Finding,
        Severity,
    )

    base = _report(tmp_path, OPENAPI_V1)
    f1 = Finding(
        id="OAS001", title="t", description="d1",
        severity=Severity.LOW, confidence=base.findings[0].confidence
        if base.findings else __import__(
            "forge_doctor_api.core.models", fromlist=["Confidence"]
        ).Confidence.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
    )
    cur = replace(base, findings=(*base.findings, f1))
    delta = compute_delta(base, cur)
    assert any(k.startswith("OAS001") for k in delta.findings_added)
    back = compute_delta(cur, base)
    assert any(k.startswith("OAS001") for k in back.findings_removed)


def test_delta_sorted_and_deterministic(tmp_path: Path) -> None:
    a = _report(tmp_path / "a", OPENAPI_V1)
    b = _report(tmp_path / "b", OPENAPI_V2)
    d1 = compute_delta(a, b)
    d2 = compute_delta(a, b)
    assert d1 == d2
    for field in ("findings_added", "findings_removed",
                  "unknowns_added", "unknowns_removed"):
        vals = getattr(d1, field)
        assert list(vals) == sorted(vals)
