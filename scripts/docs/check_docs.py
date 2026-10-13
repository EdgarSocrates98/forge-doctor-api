"""check_docs.py — documentation-as-code gate (Standard v1 §10, Phase 12).

Deterministic, no-LLM checks. Fails (exit 1) on:

  1. CLI drift — commands in markdown fences that don't exist in
     ``docs/reference/commands.generated.json`` (documented-but-missing).
  2. Broken internal links — ``](relative/path.md)`` targets that resolve
     to nothing, and ``#anchors`` not present in the target file.
  3. ``status:`` frontmatter claims — ``status: available`` on a
     command page whose command is not in the inventory.

Explicitly NOT checked (fragile): formatting, line length, prose style.

Usage::

    python check_docs.py --repo . --inventory docs/reference/commands.generated.json \
        --cli theforge
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FENCE_CMD = re.compile(
    r"^(\s{0,4})([a-z][a-z0-9_-]*)\s+"
    r"([a-z][a-z0-9-]*(?:\s+[a-z][a-z0-9-]*)?)\s*$",
    re.IGNORECASE)
LINK = re.compile(r"\]\(([^)#\s]+)(#[^)\s]*)?\)")
ANCHOR = re.compile(r"[^\w -]", re.UNICODE)  # GitHub slugger keeps unicode letters


def _anchorify(h: str) -> str:
    return ANCHOR.sub("", h.strip().lower()).replace(" ", "-")


def _anchors(text: str) -> set[str]:
    return {_anchorify(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)}


def check_links(repo: Path, files: list[Path]) -> list[str]:
    errs: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in LINK.finditer(text):
            target, anchor = m.group(1), m.group(2)
            if re.match(r"^[a-z]+://|mailto:", target):
                continue
            t = (f.parent / target).resolve()
            if not t.exists():
                errs.append(f"{f.relative_to(repo)}: broken link -> {target}")
                continue
            if anchor and t.suffix == ".md":
                anchors = _anchors(t.read_text(encoding="utf-8", errors="replace"))
                if _anchorify(anchor[1:]) not in anchors:
                    errs.append(f"{f.relative_to(repo)}: missing anchor {anchor} in {target}")
    return errs


def check_commands(files: list[Path], real: set[str], cli: str) -> list[str]:
    """Fenced ``<cli> <verb...>`` lines must be real command prefixes."""
    errs: list[str] = []
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = FENCE_CMD.match(line)
            if not m or m.group(2) != cli:
                continue
            words = m.group(3).split()
            found = next(
                (
                    " ".join(words[: n + 1])
                    for n in range(len(words) - 1, -1, -1)
                    if " ".join(words[: n + 1]) in real
                ),
                None,
            )
            if not found:
                errs.append(f"{f.name}:{i}: `{m.group(2)} {m.group(3)}` not a real command")
    return errs


def check_status_claims(files: list[Path], real: set[str], cli: str) -> list[str]:
    errs: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        fm = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not fm:
            continue
        m = re.search(r"^id:\s*(\S+)\s*$", fm.group(1), re.MULTILINE)
        s = re.search(r"^status:\s*(\S+)\s*$", fm.group(1), re.MULTILINE)
        if m and s and s.group(1) == "available":
            cmd = m.group(1).split(".", 1)[-1].replace(".", " ")
            if cmd not in real:
                errs.append(f"{f.name}: claims `status: available` for nonexistent `{cli} {cmd}`")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--cli", required=True)
    ap.add_argument("--docs", default="docs,README.md")
    ap.add_argument("--exclude", default="archive,superpowers/plans,superpowers/specs,historico",
                    help="comma-separated path fragments to skip (frozen/archived docs)")
    a = ap.parse_args()
    repo = Path(a.repo)
    inv = json.loads((repo / a.inventory).read_text(encoding="utf-8"))
    real = {c["path"] for c in inv["commands"]}
    files: list[Path] = []
    excl = [x.strip().lower() for x in a.exclude.split(",") if x.strip()]
    for spec in a.docs.split(","):
        p = repo / spec.strip()
        files += sorted(p.rglob("*.md")) if p.is_dir() else ([p] if p.exists() else [])
    files = [
        f for f in files
        if not any(x in f.relative_to(repo).as_posix().lower() for x in excl)
    ]

    errs = (
        check_links(repo, files)
        + check_commands(files, real, a.cli)
        + check_status_claims(files, real, a.cli)
    )
    for e in errs:
        print(f"FAIL {e}")
    print(f"check_docs: {len(errs)} problem(s) across {len(files)} file(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
