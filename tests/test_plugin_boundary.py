"""Spec 084 — plugin trust hardening: import-gating proof, dynamic
failure matrix, no-network/no-mutation proofs, output validation.

The binding invariant: **untrusted plugin code is never imported.**
Manifests are data — parsed without importing; `activate()` is the
single gate and `plugins/trust.py::load_plugin` is the single dynamic
import site. These tests prove the invariant structurally (AST over
all of src/) and behaviorally (import spy on activation paths).
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import typer.testing

from forge_doctor_api.cli import app
from forge_doctor_api.core.models import ModelError
from forge_doctor_api.plugins.conformance import (
    plugin_run_surface,
    run_conformance,
)
from forge_doctor_api.plugins.manifest import parse_manifest
from forge_doctor_api.plugins.registry import discover_registry
from forge_doctor_api.plugins.validation import (
    PLUGIN_RESULT_BUDGET,
    validate_plugin_output,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "forge_doctor_api"

# The single allowlisted site for *arbitrary* dynamic imports —
# anywhere else, a dynamic import may only target a literal
# `forge_doctor_api.*` prefix (internal lazy catalogs, never a
# plugin-supplied module path).
_DYNAMIC_IMPORT_SITES = {"plugins/trust.py"}
_INTERNAL_PREFIX = "forge_doctor_api."


def _import_target_prefix(node: ast.Call) -> str | None:
    """Static prefix of the first arg to a dynamic-import call:
    literal string or f-string constant head. None when dynamic."""
    if not node.args:
        return None
    arg = node.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr) and arg.values and isinstance(
            arg.values[0], ast.Constant) and isinstance(
            arg.values[0].value, str):
        return arg.values[0].value
    return None

# Modules the Doctor must never import — sibling-product or
# orchestration packages would invert the boundary direction.
_EXTERNAL_ROOTS = {
    "forge_doctor_data", "forger", "the_forger", "api_forge",
    "api_forge_studio", "orchestrator",
}

VALID = """
[tool.forge-doctor.plugin]
id = "demo-plugin"
version = "1.0.0"
module = "forge_doctor_api.sdk"
doctor_api = ">=0.1"
capabilities = ["framework-adapter"]
trust_class = "BUILTIN"
"""

UNTRUSTED_TOML = """
[tool.forge-doctor.plugin]
id = "shady"
version = "0.1.0"
module = "nonexistent_module_xyz"
trust_class = "UNTRUSTED"
"""

runner = typer.testing.CliRunner()


def _write(tmp_path: Path, name: str, text: str) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "pyproject.toml"
    f.write_text(text, encoding="utf-8")
    return f


def _tree_hash(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(
        p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()}


def _iter_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _call_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in _iter_calls(tree):
        func = node.func
        if isinstance(func, ast.Name):
            names.append(func.id)
        elif isinstance(func, ast.Attribute):
            names.append(func.attr)
    return names


# -- AST: the import gate -----------------------------------------------------


def test_dynamic_import_only_at_trust_gate() -> None:
    """Plugin modules can only be reached through the trust gate.

    `importlib.import_module`/`__import__` outside `plugins/trust.py`
    may only import with a static `forge_doctor_api.` prefix — lazy
    internal catalogs, never a manifest-declared plugin path. Any
    dynamic or non-package target is a trust-boundary breach.
    (importlib.metadata entry_points reads *metadata* — it never
    imports — and is not in scope.)
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _iter_calls(tree):
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute)
                    else "")
            if name not in ("import_module", "__import__"):
                continue
            if rel in _DYNAMIC_IMPORT_SITES:
                continue
            prefix = _import_target_prefix(node)
            if name == "__import__" or not prefix or not (
                    prefix.startswith(_INTERNAL_PREFIX)
                    or prefix == "forge_doctor_api"):
                offenders.append(
                    f"{rel}:L{node.lineno}: {name}() target not "
                    "provably first-party")
    assert offenders == [], "\n".join(offenders)


def test_no_external_orchestration_imports() -> None:
    """No src/ module imports sibling-product/orchestration packages."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".")[0]]
            for root in roots:
                if root in _EXTERNAL_ROOTS:
                    offenders.append(f"{rel}: import {root}")
    assert offenders == [], "\n".join(offenders)


def test_plugins_package_never_imports_plugin_paths() -> None:
    """Only the trust gate may dynamically import; the registry reads
    importlib *metadata* (never module code); every other plugins/
    module is clean of dynamic-import machinery entirely."""
    offenders: list[str] = []
    for path in sorted(SRC.glob("plugins/*.py")):
        if path.name == "trust.py":
            continue  # the allowlisted gate itself
        text = path.read_text(encoding="utf-8")
        for banned in ("__import__", "import_module"):
            if banned in text:
                offenders.append(f"{path.name}: {banned}")
        if "importlib" in text and path.name != "registry.py":
            offenders.append(f"{path.name}: importlib")
    # registry.py holds importlib.metadata only (asserted by the
    # allowlist in test_boundary.py::_IMPORTLIB_ALLOWLIST).
    assert offenders == [], f"dynamic-import surface: {offenders}"


# -- failure matrix -----------------------------------------------------------


def test_matrix_success(tmp_path: Path) -> None:
    _write(tmp_path, "demo", VALID)
    registry = discover_registry(tmp_path)
    module = registry.activate("demo-plugin")
    assert module.__name__ == "forge_doctor_api.sdk"


def test_matrix_import_failure_typed_and_unimported(
        tmp_path: Path) -> None:
    """APPROVED_LOCAL plugin pointing at a missing module fails with a
    typed error — and the module never enters sys.modules."""
    _write(tmp_path, "ghost", """
[tool.forge-doctor.plugin]
id = "ghost"
version = "1.0.0"
module = "no_such_module_xyz"
trust_class = "APPROVED_LOCAL"
source = "plugins/ghost"
""")
    registry = discover_registry(tmp_path)
    with pytest.raises(ModelError, match="failed to import"):
        registry.activate("ghost")
    assert "no_such_module_xyz" not in sys.modules


def test_matrix_incompatible_doctor_api(tmp_path: Path) -> None:
    _write(tmp_path, "future", VALID.replace(
        'id = "demo-plugin"', 'id = "future"').replace(
        'doctor_api = ">=0.1"', 'doctor_api = ">=9.9"'))
    registry = discover_registry(tmp_path)
    manifest = registry.get("future")
    assert manifest is not None
    assert not registry.compatible(manifest)
    with pytest.raises(ModelError, match="requires doctor_api"):
        registry.activate("future")


def test_matrix_invalid_manifest_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "bad", "[tool.forge-doctor.plugin]\nid = !!!\n")
    registry = discover_registry(tmp_path)
    assert registry.get("bad") is None
    assert registry.rejections


def test_matrix_duplicate_id_conflicts(tmp_path: Path) -> None:
    _write(tmp_path, "a", VALID)
    _write(tmp_path, "b", VALID.replace(
        'module = "forge_doctor_api.sdk"',
        'module = "forge_doctor_api.cli"'))
    registry = discover_registry(tmp_path)
    assert any(c.kind == "duplicate-id"
               and "demo-plugin" in c.detail
               for c in registry.conflicts())


def test_matrix_timeout_is_cooperative_and_documented() -> None:
    """The plugin surface is synchronous: no threads, signals, or
    async — a runaway plugin is a conformance-harness concern, not a
    per-call timeout (documented, not faked)."""
    offenders: list[str] = []
    for path in sorted(SRC.glob("plugins/*.py")):
        rel = f"plugins/{path.name}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        banned = {"threading", "signal", "asyncio", "multiprocessing",
                  "concurrent"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in banned:
                        offenders.append(f"{rel}: {a.name}")
            elif isinstance(node, ast.ImportFrom) and (
                    node.module or "").split(".")[0] in banned:
                offenders.append(f"{rel}: from {node.module}")
    assert offenders == [], (
        "plugin surface gained async/threading machinery — revisit "
        f"timeout policy: {offenders}")


def test_matrix_non_model_result_flagged(tmp_path: Path) -> None:
    """A result that isn't a mapping/list is a violation, not a
    crash — serialized form is the contract."""
    assert validate_plugin_output(42, tmp_path)[0].rule == "result-type"
    assert validate_plugin_output("oops", tmp_path)[0].rule == (
        "result-type")
    bad_shape = validate_plugin_output(
        {"findings": "not-a-list"}, tmp_path)
    assert any(v.rule == "findings-type" for v in bad_shape)


def test_matrix_oversized_result_bounded(tmp_path: Path) -> None:
    """Over-budget output is a typed violation — the budget is real."""
    huge = {"findings": [
        {"id": "OAS001", "title": "x" * 4096, "severity": "LOW",
         "confidence": "HIGH", "evidence_kind": "STATIC",
         "evidence": [{"kind": "STATIC", "source": "s",
                       "summary": "pad"}]}
        for _ in range((PLUGIN_RESULT_BUDGET // 4096) + 8)]}
    violations = validate_plugin_output(huge, tmp_path)
    assert any(v.rule == "oversized" for v in violations)


def test_matrix_crash_is_typed_no_traceback(tmp_path: Path) -> None:
    def _boom(ctx, files):
        raise RuntimeError("plugin exploded at /internal/path")

    report = run_conformance("boom", _boom, tmp_path)
    assert report.checks[0].name == "run"
    assert report.checks[0].status == "error"
    assert "Traceback" not in report.checks[0].details
    assert "File \"" not in report.checks[0].details


# -- no-network / no-mutation -------------------------------------------------


_PLUGIN_SRC = (Path(__file__).resolve().parent / "fixtures"
               / "plugin_src")

LOCAL = """
[tool.forge-doctor.plugin]
id = "demo-local"
version = "1.0.0"
module = "demoplug"
doctor_api = ">=0.1"
capabilities = ["framework-adapter"]
trust_class = "APPROVED_LOCAL"
source = "plugins/demo-local"
"""


def _plugin_fixture(tmp_path: Path) -> Path:
    """plugins/ dir with an APPROVED_LOCAL manifest whose module lives
    in tests/fixtures/plugin_src (imported via patched sys.path)."""
    plugins = tmp_path / "plugins"
    _write(plugins, "demo-local", LOCAL)
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/x')\ndef x(): pass\n", encoding="utf-8")
    return plugins


def test_plugin_commands_run_with_network_blocked(
        tmp_path: Path) -> None:
    """list/inspect/verify never touch the network — verify included:
    the full manifest→trust→import→conformance path stays offline."""
    plugins = _plugin_fixture(tmp_path)

    def _blocked(*_a, **_k):
        raise OSError("network is disabled")

    sys.modules.pop("demoplug", None)
    with patch.object(sys, "path", [*sys.path, str(_PLUGIN_SRC)]), \
            patch("socket.socket", _blocked), \
            patch("socket.create_connection", _blocked), \
            patch("socket.getaddrinfo", _blocked):
        r = runner.invoke(
            app, ["plugins", "list", "--dir", str(plugins)])
        assert r.exit_code == 0, r.output[:400]
        r = runner.invoke(
            app, ["plugins", "inspect", "demo-local",
                  "--dir", str(plugins)])
        assert r.exit_code == 0, r.output[:400]
        r = runner.invoke(
            app, ["plugins", "verify", "demo-local", str(tmp_path),
                  "--dir", str(plugins)])
        assert r.exit_code == 0, r.output[:400]


def test_plugin_commands_do_not_mutate_project(tmp_path: Path) -> None:
    """sha256 tree of the project is identical before/after list,
    inspect, verify, and a direct conformance run."""
    plugins = _plugin_fixture(tmp_path)
    before = _tree_hash(tmp_path)

    sys.modules.pop("demoplug", None)
    with patch.object(sys, "path", [*sys.path, str(_PLUGIN_SRC)]):
        for argv in (
            ["plugins", "list", "--dir", str(plugins)],
            ["plugins", "inspect", "demo-local",
             "--dir", str(plugins)],
            ["plugins", "verify", "demo-local", str(tmp_path),
             "--dir", str(plugins)],
        ):
            result = runner.invoke(app, argv)
            assert result.exit_code == 0, result.output[:400]
            assert _tree_hash(tmp_path) == before

        registry = discover_registry(plugins)
        module = registry.activate("demo-local")
        run = plugin_run_surface(module)
        assert run is not None
        report = run_conformance("demo-local", run, tmp_path)
        assert report.passed
    assert _tree_hash(tmp_path) == before


def test_untrusted_listed_but_never_imported(tmp_path: Path) -> None:
    """UNTRUSTED manifests list and inspect, but activation refuses
    before any import — verified with an import spy."""
    plugins = tmp_path / "plugins"
    _write(plugins, "shady", UNTRUSTED_TOML)
    registry = discover_registry(plugins)
    assert registry.get("shady") is not None

    imported: list[str] = []
    real_import = __import__

    def _spy(name: str, *a: object, **k: object) -> object:
        imported.append(name)
        return real_import(name, *a, **k)

    with patch("builtins.__import__", side_effect=_spy), \
            pytest.raises(ModelError, match="UNTRUSTED"):
        registry.activate("shady")
    assert "nonexistent_module_xyz" not in imported
    assert "nonexistent_module_xyz" not in sys.modules


# -- output validation ---------------------------------------------------------


def _good_finding() -> dict:
    return {
        "id": "OAS001", "title": "t", "description": "d",
        "severity": "LOW", "confidence": "MEDIUM",
        "evidence_kind": "STATIC",
        "evidence": [{"kind": "STATIC", "source": "api.yaml",
                      "summary": "seen"}],
        "entity_ids": ["operation:openapi:listPets"],
        "source_location": {"path": "api.yaml", "line": 5},
    }


def test_output_validation_accepts_clean(tmp_path: Path) -> None:
    assert validate_plugin_output(
        {"findings": [_good_finding()]}, tmp_path) == ()


@pytest.mark.parametrize("mutate,rule", [
    (lambda f: f.update(severity="CATASTROPHIC"), "severity"),
    (lambda f: f.update(confidence="PRETTY_SURE"), "confidence"),
    (lambda f: f.update(evidence_kind="VIBES"), "evidence_kind"),
    (lambda f: f.update(id="not-an-id"), "check-id"),
    (lambda f: f.update(entity_ids=["no colons"]), "entity-id"),
    (lambda f: f.pop("evidence"), "evidence"),
    (lambda f: f.update(evidence=[{"kind": "VIBES", "source": "s",
                                   "summary": "x"}]),
     "evidence-kind"),
    (lambda f: f.update(source_location={"path": "../escape.py"}),
     "path-scope"),
    (lambda f: f.update(source_location={"path": "/abs/escape.py"}),
     "path-scope"),
    (lambda f: f.update(source_location={"path": "C:\\win\\x.py"}),
     "path-scope"),
    (lambda f: f.update(schema_version="99.0"), "schema-version"),
    (lambda f: f.update(confidence="UNKNOWN", unknowns=[]),
     "unknowns"),
])
def test_output_validation_rejects(tmp_path: Path,
                                   mutate, rule: str) -> None:
    f = _good_finding()
    mutate(f)
    violations = validate_plugin_output(
        {"findings": [f]}, tmp_path)
    assert any(v.rule == rule for v in violations), (
        f"expected {rule} violation in {violations}")


def test_output_validation_typed_and_sorted(tmp_path: Path) -> None:
    f = _good_finding()
    f.update(severity="NOPE", entity_ids=["bad id"])
    violations = validate_plugin_output(
        {"findings": [f]}, tmp_path)
    keys = [(v.rule, v.path) for v in violations]
    assert keys == sorted(keys)
    assert all(v.rule and v.detail for v in violations)


def test_conformance_output_schema_check(tmp_path: Path) -> None:
    """The output-schema check fails a plugin emitting bad findings."""
    def _bad(ctx, files):
        return [{"id": "not-an-id", "severity": "NOPE"}]

    report = run_conformance("bad-output", _bad, tmp_path)
    check = next(c for c in report.checks
                 if c.name == "output-schema")
    assert check.status == "fail"
    assert "check-id" in check.details or "severity" in check.details


def test_conformance_clean_still_passes_all(tmp_path: Path) -> None:
    from forge_doctor_api.analyzers.routes.fastapi import (
        FastApiAdapter,
    )
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/x')\ndef x(): pass\n", encoding="utf-8")

    def _clean(ctx, files):
        return FastApiAdapter().discover_routes(ctx, "conf", files)

    report = run_conformance("clean", _clean, tmp_path)
    for c in report.checks:
        assert c.status == "pass", f"{c.name}: {c.details}"
    assert {c.name for c in report.checks} == {
        "determinism", "offline", "evidence", "side-effects",
        "output-compat", "unknown-semantics", "output-schema"}


def test_manifest_json_roundtrip_stable(tmp_path: Path) -> None:
    """Manifest serialization is deterministic — registry output
    stays diffable (contract-stable inventory)."""
    f = _write(tmp_path, "demo", VALID)
    manifest, errors = parse_manifest(f)
    assert errors == () and manifest is not None
    again, _ = parse_manifest(f)
    assert manifest.to_json() == again.to_json()
