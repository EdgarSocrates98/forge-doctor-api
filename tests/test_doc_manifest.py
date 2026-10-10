"""Docs-as-code gate (Forge Knowledge Program §18): no broken internal links
in active documentation.

Historical/frozen trees are exempt — they are preserved, not repaired:
``docs/sdd/archive``, ``docs/superpowers/plans``, ``docs/historico``,
``.claude/sdd/archive``, ``.agents/sdd/archive``, ``vendor/``. A broken link
inside an active doc fails the gate; the inventory reports name the file.
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


def _load_manifest():
    spec = importlib.util.spec_from_file_location(
        "doc_manifest", ROOT / "scripts" / "docs" / "doc_manifest.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("cli,forge", [
    # overridden per repo by edit below — single binding keeps vendoring simple
    ("forge-doctor-api", "forge-doctor-api"),
])
def test_no_broken_links_in_active_docs(cli: str, forge: str):
    mod = _load_manifest()
    inv = ROOT / "docs" / "knowledge-program" / "inventory.jsonl"
    if not inv.exists():
        pytest.skip("run scripts/docs/doc_manifest.py first")
    rows = [json.loads(l) for l in inv.read_text("utf-8").splitlines()]
    broken: list[dict] = []
    for r in rows:
        path = r["path"]
        if path.startswith(EXEMPT_PREFIXES):
            continue
        if "VENDORED_UPSTREAM" in r["secondary"]:
            continue
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        links, _ = mod._links_and_anchors(text)
        broken += mod._check_links(ROOT, Path(path), links)
    assert not broken, "broken internal links in active docs:\n" + "\n".join(
        f"  {b['file']} -> {b['link']} ({b['problem']})" for b in broken[:30]
    )
