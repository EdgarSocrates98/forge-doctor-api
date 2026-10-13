"""Spec 070+075 — The-Forger/API Forge boundary.

Covers: boundary AST purity (no network/subprocess/import/dynamic
execution) extended package-wide, ForgeRequest → ForgeHandoff/
ForgeResult round trip, the bounded handoff budget, first-class
DeltaContext wiring, the DoctorEndpoint dict shape, handoff → fleet
member ingestion with compact fields only, and the docs link
contract for the boundary surface.
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
from forge_doctor_api.handoff.model import ApiHandoffBundle
from forge_doctor_api.handoff.protocol import (
    ForgeHandoff,
    RequestDelta,
    build_request,
)
from forge_doctor_api.workspace.model import MemberRole, WorkspaceMember

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "forge_doctor_api"
BOUNDARY = SRC / "handoff" / "boundary.py"

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""

# --- spec 075 shared ban table -----------------------------------------
# Import roots banned across the whole src/ tree — presence anywhere
# is a boundary violation (the Doctor never calls out).
_FORBIDDEN_IMPORT_ROOTS = {
    "socket", "urllib", "http", "requests", "httpx",
    "subprocess", "shutil", "ctypes", "pickle", "os",
    # spec 084: sibling-product / orchestration packages — the Doctor
    # boundary is one-directional and never imports them.
    "forge_doctor_data", "forger", "the_forger", "api_forge",
    "api_forge_studio", "orchestrator",
}
# Bare-name calls banned everywhere — dynamic execution surfaces.
_FORBIDDEN_NAME_CALLS = {
    "exec", "eval", "compile", "__import__", "system", "popen",
    "fork", "execl", "execv", "execve", "execvp",
}
_FORBIDDEN_NAME_PREFIXES = ("spawn", "execv", "fork")
# Attribute calls banned by root object (os.system et al. — `os` is
# import-banned anyway; this list is defense in depth and documents
# intent for allowlisted modules).
_FORBIDDEN_ATTR_CALLS = {
    "os": {"system", "popen", "fork", "forkpty", "execl", "execv",
           "execve", "execvp", "spawnl", "spawnv"},
    "pickle": {"load", "loads"},
    "ctypes": {"CDLL", "PyDLL", "WinDLL", "cdll", "pydll", "windll"},
    "importlib": {"import_module"},
}
# `importlib` is allowed only in these named modules, for the
# enumerated safe uses below — everything else is a violation.
_IMPORTLIB_ALLOWLIST = {
    "core/stats.py": "lazy import of own checks.*.catalog modules",
    "knowledge/loader.py": "importlib.resources package data access",
    "lab/capabilities.py": "find_spec detection — never imports",
    "plugins/registry.py": "importlib.metadata entry-points read",
    "plugins/trust.py": "import_module gated by TrustClass verification",
}
# `boundary.py` itself is held to a stricter bar — no getattr at all.
_BOUNDARY_EXTRA_CALLS = {"getattr"}
# Vendored upstream surfaces (byte-parity with the-forge): their imports
# are sanctioned host surfaces — loopback-only Studio server, terminal UI
# kit. Audited upstream; re-banning them here would pin a false invariant.
_VENDORED = frozenset({
    "_graphstudio.py",
    "ui/i18n.py", "ui/kit.py", "ui/wizard.py", "ui/home.py",
    "ui/app.py", "ui/screen.py", "ui/tui.py",
})


def _member(tmp_path: Path) -> WorkspaceMember:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    return WorkspaceMember(
        name="svc", path=str(tmp_path), role=MemberRole.SERVICE)


def _call_name(node: ast.Call) -> tuple[str, str]:
    func = node.func
    if isinstance(func, ast.Name):
        return "", func.id
    if isinstance(func, ast.Attribute):
        root = func.value
        return (root.id if isinstance(root, ast.Name) else "",
                func.attr)
    return "", ""


def test_package_ast_purity() -> None:
    """Package-wide ban table — the boundary rules hold across src/."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in _VENDORED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in _FORBIDDEN_IMPORT_ROOTS:
                        offenders.append(f"{rel}: import {alias.name}")
                    elif root == "importlib" and rel not in (
                            _IMPORTLIB_ALLOWLIST):
                        offenders.append(
                            f"{rel}: import {alias.name} (not "
                            "allowlisted)")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    offenders.append(
                        f"{rel}: from {node.module} import ...")
                elif root == "importlib" and rel not in (
                        _IMPORTLIB_ALLOWLIST):
                    offenders.append(
                        f"{rel}: from {node.module} import ... "
                        "(not allowlisted)")
            elif isinstance(node, ast.Call):
                root, name = _call_name(node)
                if not root and (
                        name in _FORBIDDEN_NAME_CALLS or any(
                            name.startswith(p)
                            for p in _FORBIDDEN_NAME_PREFIXES)):
                    offenders.append(f"{rel}: call {name}()")
                if root in _FORBIDDEN_ATTR_CALLS and (
                        name in _FORBIDDEN_ATTR_CALLS[root]):
                    if root == "importlib" and rel in (
                            _IMPORTLIB_ALLOWLIST):
                        continue
                    offenders.append(f"{rel}: call {root}.{name}()")
                if rel == "handoff/boundary.py" and (
                        name in _BOUNDARY_EXTRA_CALLS):
                    offenders.append(f"{rel}: call {name}()")
    assert offenders == [], "package boundary violations:\n" + "\n".join(
        offenders)


def test_boundary_ast_purity() -> None:
    tree = ast.parse(BOUNDARY.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_IMPORT_ROOTS or root == "importlib":
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _FORBIDDEN_IMPORT_ROOTS or root == "importlib":
                offenders.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            root, name = _call_name(node)
            if (not root and (name in _FORBIDDEN_NAME_CALLS or any(
                    name.startswith(p)
                    for p in _FORBIDDEN_NAME_PREFIXES))) or (
                    name in _BOUNDARY_EXTRA_CALLS):
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
    bundle = boundary.handle(request)
    assert isinstance(bundle, ApiHandoffBundle)
    assert bundle.handoff_version == 2
    assert bundle.handoff_id
    handoff = boundary.envelope(request)
    assert isinstance(handoff, ForgeHandoff)
    assert handoff.handoff_id == bundle.handoff_id
    assert handoff.bundle_ref.startswith("doctor://handoff/")
    assert handoff.analysis_rev


def test_summarize_and_capabilities(tmp_path: Path) -> None:
    _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    request = build_request(
        target="svc", capabilities=("OPENAPI_32", "MTLS", "NOPE"))
    handoff = boundary.envelope(request)
    result = boundary.summarize(handoff)
    assert result.status in ("ok", "partial")
    assert result.refs
    caps = boundary.capabilities(request)
    assert caps.status == "partial"  # NOPE is not a real capability
    assert "not evidenced" in caps.summary or not caps.summary.endswith(
        "detected")


def test_bounded_handoff_caps_growth(tmp_path: Path) -> None:
    """Over-budget sections truncate deterministically into unknowns."""
    _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    bundle = boundary.handle(build_request(target="svc"))
    # default budgets cap every carried section
    from forge_doctor_api.handoff.model import HANDOFF_BUDGET
    for name, limit in HANDOFF_BUDGET.items():
        value = getattr(bundle, name, None)
        assert value is None or len(value) <= limit, name
    # deterministic: identical requests produce identical bundles
    assert boundary.handle(build_request(target="svc")) == bundle
    # truncation is recorded, never silent
    huge = ApiHandoffBundle(
        operations=tuple(f"GET /o{i}" for i in range(10)),
        findings=boundary.handle(build_request(target="svc")).findings,
        handoff_version=2,
        handoff_id="x")
    trimmed = huge.bounded({"operations": 3})
    assert len(trimmed.operations) == 3
    assert list(trimmed.operations) == sorted(trimmed.operations)
    marker = [u for u in trimmed.unknowns
              if u.subject == "handoff:operations"]
    assert marker and "budget_exceeded" in marker[0].missing
    assert trimmed.handoff_id != "x"  # identity recomputed


def test_delta_wired_into_bundle(tmp_path: Path) -> None:
    """request.delta + resolved baseline -> first-class DeltaContext."""
    _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    request = build_request(
        target="svc",
        delta=RequestDelta(
            baseline_ref="doctor://handoff/base",
            changed_files=("api.yaml",)))
    # no baseline -> explicit unknown, never a fabricated delta
    unresolved = boundary.handle(request)
    assert unresolved.delta is None
    assert any(u.subject == "delta" for u in unresolved.unknowns)
    # resolved baseline -> computed delta on the bundle
    from forge_doctor_api.scan import scan_project
    baseline = scan_project(ProjectContext.from_root(tmp_path))
    resolved = boundary.handle(request, baseline=baseline)
    assert resolved.delta is not None
    assert resolved.delta.baseline_ref == "doctor://handoff/base"
    assert resolved.delta.changed_files == ("api.yaml",)


def test_endpoint_dict_shape(tmp_path: Path) -> None:
    """DoctorEndpoint: {request, handoff, capabilities, manifest}."""
    _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    request = build_request(target="svc", request_id="ep1")
    endpoint = boundary.endpoint_dict(request)
    assert set(endpoint) == {
        "request", "handoff", "capabilities", "manifest"}
    assert endpoint["request"]["request_id"] == "ep1"
    assert endpoint["handoff"]["handoff_id"]
    # manifest is a conforming forge-contracts/1 diagnostic-manifest
    from forge_doctor_api.contracts.validate import validate_named
    assert validate_named(
        endpoint["manifest"], "diagnostic-manifest") == []


def test_handoff_to_fleet_member(tmp_path: Path) -> None:
    member = _member(tmp_path)
    boundary = DoctorBoundary(
        context=ProjectContext.from_root(tmp_path))
    handoff = boundary.envelope(build_request(target="svc"))
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
