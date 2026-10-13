"""Docs-as-code drift gate (Forge Knowledge Program §10): fenced
``<cli> <verb>`` invocations in *active* docs must be real verbs of the
live parser — walked by ``doc_inventory.py``, never regex over source.

Frozen trees are exempt (same prefixes as ``test_doc_manifest.py``);
generated mirrors and vendored upstream docs are not scanned because the
manifest marks them ``GENERATED`` / ``VENDORED_UPSTREAM``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXEMPT_PREFIXES = (
    "docs/sdd/archive/", "docs/superpowers/", "docs/historico/",
    ".claude/sdd/", ".agents/sdd/", ".devin/sdd/", "vendor/",
    "docs/reports/", "docs/knowledge-program/", "knowledge/devin/",
)

# per-repo binding — same shape as test_doc_manifest.py
FORGE = "forge-doctor-api"
CLI_ALIASES = ("forge-doctor-api",)
PARSER = ("typer", "forge_doctor_api.cli:app")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _commands(mod) -> list[dict]:
    kind, spec = PARSER
    out: list[dict] = []
    if kind == "argparse":
        factory = mod._resolve(spec)
        mod.walk_argparse(factory() if callable(factory) else factory, "", out)
    else:
        import typer.main
        mod.walk_click(typer.main.get_command(mod._resolve(spec)), "", out)
    return out


def _active_docs() -> list[Path]:
    inv = ROOT / "docs" / "knowledge-program" / "inventory.jsonl"
    if not inv.exists():
        pytest.skip("run scripts/docs/doc_manifest.py first")
    out: list[Path] = []
    for line in inv.read_text("utf-8").splitlines():
        r = json.loads(line)
        path = r["path"]
        if path.startswith(EXEMPT_PREFIXES):
            continue
        if "VENDORED_UPSTREAM" in r.get("secondary", []):
            continue
        if r.get("category") == "GENERATED":
            continue
        if not path.endswith(".md"):
            continue
        p = ROOT / path
        if p.exists():
            out.append(p)
    return out


def test_no_documented_missing_verbs():
    mod = _load("doc_inventory", ROOT / "scripts" / "docs" / "doc_inventory.py")
    commands = _commands(mod)
    real_first = {c["path"].split()[0] for c in commands}
    files = _active_docs()
    missing: list[str] = []
    for alias in CLI_ALIASES:
        verbs, where = mod._doc_verbs(alias, files)
        for v in sorted(verbs - real_first):
            missing.append(f"`{alias} {v}` at {'; '.join(sorted(set(where[v]))[:3])}")
    assert not missing, (
        "docs invoke verbs the real CLI does not have "
        f"({FORGE}, {len(files)} active docs):\n  " + "\n  ".join(missing[:30])
    )
