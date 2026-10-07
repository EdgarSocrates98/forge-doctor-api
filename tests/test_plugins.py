"""Specs 053-054 — plugin manifests, registry, trust gate, conformance."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from forge_doctor_api.core.models import ModelError
from forge_doctor_api.plugins.conformance import (
    plugin_run_surface,
    run_conformance,
)
from forge_doctor_api.plugins.manifest import parse_manifest
from forge_doctor_api.plugins.registry import discover_registry
from forge_doctor_api.plugins.trust import TrustClass

VALID = """
[tool.forge-doctor.plugin]
id = "demo-plugin"
version = "1.0.0"
module = "forge_doctor_api.analyzers.routes.fastapi"
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

ELEVATED = """
[tool.forge-doctor.plugin]
id = "liar"
version = "1.0.0"
module = "os"
trust_class = "BUILTIN"
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "pyproject.toml"
    f.write_text(text, encoding="utf-8")
    return f


def test_valid_manifest_parses(tmp_path: Path) -> None:
    f = _write(tmp_path, "demo", VALID)
    manifest, errors = parse_manifest(f)
    assert errors == ()
    assert manifest is not None
    assert manifest.plugin_id == "demo-plugin"
    assert manifest.trust is TrustClass.BUILTIN


def test_self_elevation_is_downgraded(tmp_path: Path) -> None:
    f = _write(tmp_path, "liar", ELEVATED)
    manifest, errors = parse_manifest(f)
    assert manifest is None
    assert any("BUILTIN" in e.reason for e in errors)


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    f = _write(tmp_path, "bad", VALID + 'backdoor = "x"\n')
    manifest, errors = parse_manifest(f)
    assert manifest is None
    assert any("unknown manifest keys" in e.reason for e in errors)


def test_missing_table_rejected(tmp_path: Path) -> None:
    f = _write(tmp_path, "plain", "[project]\nname = 'x'\n")
    manifest, errors = parse_manifest(f)
    assert manifest is None
    assert errors


def test_registry_discovers_and_lists(tmp_path: Path) -> None:
    _write(tmp_path, "a", VALID)
    _write(tmp_path, "b", UNTRUSTED_TOML)
    registry = discover_registry(tmp_path)
    assert {m.plugin_id for m in registry.list()} == {
        "demo-plugin", "shady"}


def test_untrusted_never_imported(tmp_path: Path) -> None:
    _write(tmp_path, "shady", UNTRUSTED_TOML)
    registry = discover_registry(tmp_path)
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


def test_activation_of_trusted_builtin(tmp_path: Path) -> None:
    _write(tmp_path, "demo", VALID)
    registry = discover_registry(tmp_path)
    module = registry.activate("demo-plugin")
    assert module.__name__.endswith("routes.fastapi")


def test_conflicts_surface(tmp_path: Path) -> None:
    dup = VALID.replace('id = "demo-plugin"', 'id = "demo-plugin"')
    _write(tmp_path, "a", dup)
    _write(tmp_path, "b", dup.replace(
        'module = "forge_doctor_api.analyzers.routes.fastapi"',
        'module = "forge_doctor_api.sdk"'))
    registry = discover_registry(tmp_path)
    assert any(c.kind == "duplicate-id" for c in registry.conflicts())


# -- conformance (spec 054) ----------------------------------------------------


def _clean_run(ctx, files):
    from forge_doctor_api.analyzers.routes.fastapi import FastApiAdapter
    return FastApiAdapter().discover_routes(ctx, "conf", files)


def test_conformance_clean_plugin_passes(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/x')\ndef x(): pass\n", encoding="utf-8")
    report = run_conformance("clean", _clean_run, tmp_path)
    for c in report.checks:
        assert c.status == "pass", f"{c.name}: {c.details}"


def test_conformance_nondeterministic_fails(tmp_path: Path) -> None:
    counter = {"n": 0}

    def _noisy(ctx, files):
        counter["n"] += 1
        return [counter["n"]]

    report = run_conformance("noisy", _noisy, tmp_path)
    det = next(c for c in report.checks if c.name == "determinism")
    assert det.status == "fail"


def test_conformance_side_effects_fail(tmp_path: Path) -> None:
    def _writer(ctx, files):
        (tmp_path / "pollution.txt").write_text("x")
        return []

    report = run_conformance("writer", _writer, tmp_path)
    se = next(c for c in report.checks if c.name == "side-effects")
    assert se.status == "fail"


def test_conformance_run_error_reported(tmp_path: Path) -> None:
    def _boom(ctx, files):
        raise RuntimeError("plugin exploded")

    report = run_conformance("boom", _boom, tmp_path)
    assert not report.passed
    assert report.checks[0].name == "run"
    assert report.checks[0].status == "error"


def test_conformance_evidence_check_passes_valid(tmp_path: Path) -> None:
    from forge_doctor_api.core.models import (
        Confidence,
        Evidence,
        EvidenceKind,
        Finding,
        Severity,
        SourceLocation,
        UnknownFact,
    )

    def _valid(ctx, files):
        return [Finding(
            id="TST001", title="t", description="d",
            severity=Severity.LOW, confidence=Confidence.MEDIUM,
            evidence_kind=EvidenceKind.STATIC,
            evidence=(Evidence(
                kind=EvidenceKind.STATIC, source="x",
                summary="seen"),),
            unknowns=(UnknownFact(
                subject="x", missing="y", resolution="z"),),
            entity_ids=("op:x",),
            source_location=SourceLocation(path="x"))]

    report = run_conformance("valid", _valid, tmp_path)
    ev = next(c for c in report.checks if c.name == "evidence")
    assert ev.status == "pass"


def test_conformance_offline_fails_for_network(tmp_path: Path) -> None:
    def _net(ctx, files):
        import socket as s
        return s.getaddrinfo("example.com", 80)

    report = run_conformance("net", _net, tmp_path)
    off = next(c for c in report.checks if c.name == "offline")
    assert off.status == "fail"


def test_plugin_run_surface_adapter(tmp_path: Path) -> None:
    from forge_doctor_api.analyzers.routes.fastapi import FastApiAdapter
    run = plugin_run_surface(FastApiAdapter())
    assert callable(run)
