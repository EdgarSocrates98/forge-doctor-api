#!/usr/bin/env python3
"""regen_docs.py — one-shot regeneration of every docs-as-code artifact.

Runs the whole deterministic pipeline in dependency order so contributors
need exactly one command after changing docs or the CLI parser:

    python scripts/docs/regen_docs.py

Per-repo wiring lives in ``docs/knowledge-program/pipeline.json`` —
the script itself is identical across Forge repos (vendored).

pipeline.json::

    {
      "forge_id": "the-forge",
      "cli": "forge",
      "parser": "argparse:theforge.cli.main:build_parser",
      "docs": ["docs", "README.md"],
      "steps": {
        "inventory": true,      // commands.generated.json + divergence
        "manifest": true,       // inventory.jsonl + reports + context-map
        "index": true,          // docs/INDEX.md
        "hub": false,           // which-forge.md (the-forge only)
        "final_report": true    // knowledge-program/final-report.md
      }
    }

stdlib-only; safe to vendor verbatim into any Forge repo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "docs" / "knowledge-program" / "pipeline.json"
DOCS_SCRIPTS = ROOT / "scripts" / "docs"


def _python() -> str:
    """The repo venv interpreter — the parser spec imports the package."""
    for cand in (ROOT / ".venv" / "Scripts" / "python.exe",
                 ROOT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def _run(script: str, args: list[str]) -> None:
    cmd = [_python(), str(DOCS_SCRIPTS / script), *args]
    print(f"$ {' '.join([script, *args])}")
    cp = subprocess.run(cmd, cwd=ROOT, check=False)  # noqa: S603 -- argv fixo, sem shell
    if cp.returncode != 0:
        raise SystemExit(f"regen_docs: {script} failed ({cp.returncode})")


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    forge, cli = cfg["forge_id"], cfg["cli"]
    steps = cfg.get("steps", {})

    if steps.get("inventory", True):
        kind, _, spec = cfg["parser"].partition(":")
        args = ["--forge", forge, "--cli", cli,
                f"--{kind}", spec,
                "--out", "docs/reference/commands.generated.json",
                "--divergence", *cfg.get("docs", ["docs", "README.md"])]
        _run("doc_inventory.py", args)

    if steps.get("reference", True):
        _run("doc_reference.py", [
            "--inventory", "docs/reference/commands.generated.json",
            "--out", "docs/reference/commands.md", "--cli", cli,
            "--rationale", "docs/reference/command-rationale.json"])

    if steps.get("manifest", True):
        _run("doc_manifest.py", [
            "--repo", ".", "--forge", forge, "--cli", cli,
            "--out", "docs/knowledge-program"])

    if steps.get("index", True):
        _run("doc_index.py", ["--repo", ".", "--forge", forge])

    if steps.get("hub", False):
        _run("gen_hub.py", [])

    if steps.get("final_report", True):
        _run("final_report.py", ["--forge", forge])

    print(f"regen_docs: {forge} artifacts regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
