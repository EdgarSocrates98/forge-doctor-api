"""Spec 070 — The-Forger/API Forge boundary.

Covers: boundary AST purity (no network/subprocess/import/dynamic
execution), ForgeRequest → ForgeHandoff/ForgeResult round trip,
handoff → fleet member ingestion with compact fields only, and the
docs link contract for the boundary surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.fleet.collect import collect_handoff
from forge_doctor_api.handoff.boundary import (
    DoctorBoundary,
    handoff_to_member_fields,
)
from forge_doctor_api.handoff.protocol import (
    ForgeHandoff,
    build_request,
)
from forge_doctor_api.workspace.model import MemberRole, WorkspaceMember

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = ROOT / "src" / "forge_doctor_api" / "handoff" / "boundary.py"

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""

_FORBIDDEN_ROOTS = {
    "socket", "urllib", "http", "requests", "httpx",
    "subprocess", "importlib", "shutil", "ctypes", "pickle",
}
_FORBIDDEN_CALLS = {"exec", "eval", "compile", "system", "popen",
                    "spawn", "fork", "getattr"}


def _member(tmp_path: Path) -> WorkspaceMember:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    return WorkspaceMember(
        name="svc", path=str(tmp_path), role=MemberRole.SERVICE)


def test_boundary_ast_purity() -> None:
    tree = ast.parse(BOUNDARY.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_ROOTS:
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _FORBIDDEN_ROOTS:
                offenders.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute)
                    else "")
            if name in _FORBIDDEN_CALLS:
                offenders.append(f"call {name}()")
    assert offenders == [], "boundary imports/calls: " + ", ".join(
        offenders)


def test_boundary_no_dynamic_imports() -> None:
    text = BOUNDARY.read_text(encoding="utf-8")
    assert "__import__" not in text
    assert "importlib" not in text


def test_request_to_handoff_round_trip(tmp_path: Path) -> None:
    _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    request = build_request(
        target="svc", request_id="r1",
        capabilities=("OPENAPI_32", "MTLS"))
    handoff = boundary.handle(request)
    assert isinstance(handoff, ForgeHandoff)
    assert handoff.handoff_id
    assert handoff.bundle_ref.startswith("doctor://handoff/")
    assert handoff.analysis_rev


def test_summarize_and_capabilities(tmp_path: Path) -> None:
    _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    request = build_request(
        target="svc", capabilities=("OPENAPI_32", "MTLS", "NOPE"))
    handoff = boundary.handle(request)
    result = boundary.summarize(handoff)
    assert result.status in ("ok", "partial")
    assert result.refs
    caps = boundary.capabilities(request)
    assert caps.status == "partial"  # NOPE is not a real capability
    assert "not evidenced" in caps.summary or not caps.summary.endswith(
        "detected")


def test_handoff_to_fleet_member(tmp_path: Path) -> None:
    member = _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    handoff = boundary.handle(build_request(target="svc"))
    data = collect_handoff(member, handoff)
    # only compact fields — unevidenced models stay absent (unknown)
    assert data.openapi is None
    assert data.security is None
    assert data.reliability is None
    fields = handoff_to_member_fields(handoff)
    assert fields["analysis_rev"] == handoff.analysis_rev
    assert set(fields) <= {"styles", "unknown_subjects",
                          "analysis_rev", "handoff_id"}


def test_boundary_doc_exists_and_links() -> None:
    doc = ROOT / "docs" / "forger-boundary.md"
    text = doc.read_text(encoding="utf-8")
    for cap in ("observe", "normalize", "detect", "measure",
                "diagnose", "classify", "impact", "unknowns",
                "context"):
        assert cap in text
    for shape in ("ForgeRequest", "ForgeHandoff", "ForgeReceipt"):
        assert shape in text
    # boundary module must exist at the documented path
    assert BOUNDARY.is_file()
