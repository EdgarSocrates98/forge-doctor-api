#!/usr/bin/env python3
"""Forge Knowledge Program — per-repo final report (§25).

Derives every quantitative field from real artifacts — inventory.jsonl,
divergence.generated.json, git — and marks what is automatic vs reviewed.
Honest by construction: review levels come from the inventory rows, never
inflated.

stdlib-only; safe to vendor verbatim into any Forge repo.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def build_report(repo: Path, forge: str, out_dir: Path) -> str:
    rows = [json.loads(l) for l in
            (out_dir / "inventory.jsonl").read_text("utf-8").splitlines()
            if l.strip()]
    cats = Counter(r["category"] for r in rows)
    levels = Counter(r["review_level"] for r in rows)
    vendored = sum(1 for r in rows if "VENDORED_UPSTREAM" in r["secondary"])
    generated = sum(1 for r in rows if r["category"] == "GENERATED")

    div_path = repo / "docs" / "reference" / "divergence.generated.json"
    div = {}
    if div_path.exists():
        div = json.loads(div_path.read_text("utf-8"))

    bl_path = out_dir / "broken-link-report.md"
    bl_count = 0
    if bl_path.exists():
        bl_count = sum(1 for l in bl_path.read_text("utf-8").splitlines()
                       if l.startswith("| `"))
    dup_path = out_dir / "duplicate-content-report.md"
    dup_count = 0
    if dup_path.exists():
        dup_count = sum(1 for l in dup_path.read_text("utf-8").splitlines()
                        if l.startswith("## Group"))

    learn = sorted(r["path"] for r in rows if r["path"].startswith("docs/learn/"))
    first_runs = [r["path"] for r in rows
                  if "first-run" in r["path"] or "quickstart" in r["path"]]
    hub = sorted(r["path"] for r in rows if r["path"].startswith("docs/hub/"))

    # active-tree broken links = findings outside frozen prefixes
    frozen = ("docs/sdd/", "docs/superpowers/", ".claude/sdd/",
              "docs/historico/", "docs/reports/", "vendor/",
              "docs/knowledge-program/", "knowledge/devin/")
    active_broken = 0
    if bl_path.exists():
        for l in bl_path.read_text("utf-8").splitlines():
            if l.startswith("| `"):
                f = l.split("`")[1]
                if not f.startswith(frozen):
                    active_broken += 1

    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git(repo, "rev-parse", "--short", "HEAD")

    # documented_missing findings inside frozen trees are reported but
    # exempt — same preservation rule as broken links (§4.5).
    active_doc_missing = sum(
        1 for f in div.get("documented_missing", [])
        if not str(f.get("file", "")).replace("\\", "/").startswith(frozen))
    status = "PASS" if (active_broken == 0 and
                        active_doc_missing == 0) else "PARTIAL"

    lines = [
        "# Forge Knowledge Program — final report",
        "",
        f"| Campo | Valor |",
        f"|---|---|",
        f"| repository | `{forge}` |",
        f"| branch | `{branch}` |",
        f"| commit | `{commit}` |",
        f"| docs inventoried | {len(rows)} (excl. GENERATED mirrors: "
        f"{len(rows) - generated}; vendored upstream: {vendored}) |",
        "",
        "## Review levels (honest)",
        "",
    ]
    for lvl in ("INVENTORIED", "AUTOMATICALLY_CHECKED",
                "TECHNICALLY_VERIFIED", "SEMANTICALLY_REVIEWED",
                "USER_JOURNEY_VALIDATED"):
        lines.append(f"- `{lvl}`: {levels.get(lvl, 0)}")
    lines += [
        "",
        "Automatic checks ran on every row; semantic review is recorded only "
        "where a human/verified pass happened — nothing is inflated.",
        "",
        "## Category counts",
        "",
    ]
    for c, n in cats.most_common():
        lines.append(f"- `{c}`: {n}")
    lines += [
        "",
        "## Findings",
        "",
        f"- duplicate groups (non-generated): {dup_count}",
        f"- broken internal links total: {bl_count} "
        f"(active docs: {active_broken}; remainder in frozen/historical trees)",
        f"- documented-but-missing commands: {len(div.get('documented_missing', []))} "
        f"(active docs: {active_doc_missing})",
        f"- undocumented public commands: {len(div.get('undocumented_commands', []))}",
        "",
        "## Educational layer delivered",
        "",
        f"- first-run/quickstart docs: {len(first_runs)}",
        f"- docs/learn/ entries: {len(learn)}",
        f"- docs/hub/ entries: {len(hub)}",
        "",
        "## Documentation changes this program",
        "",
        "- `docs/INDEX.md` — generated canonical index (7-section IA)",
        "- `docs/learn/` — learning track + problem-oriented recipes",
        "- `docs/knowledge-program/` — inventory + 8 reports + context map",
    ]
    if forge == "the-forge":
        lines += [
            "- `docs/hub/` — Learning Hub (markdown-first + optional mkdocs)",
            "- `docs/learn/zero-to-multi-specialist.md` — end-to-end guide "
            "with captured evidence",
        ]
    lines += [
        "",
        "## Tests / gates",
        "",
        "- `tests/test_doc_manifest.py` — zero broken links in active docs "
        "(frozen trees exempt)",
        "- `check_docs`/`doc_inventory` — command drift gate, parser-walked",
        "",
        "## Limitations & remaining gaps",
        "",
        "- Semantic review of the full corpus is not claimed — review levels "
        "in `inventory.jsonl` say which docs were actually reviewed.",
        "- Historical/frozen trees keep their broken links by design (§4.5 "
        "preservation) — they are reported, not repaired.",
        "- Hub site build not executed (dev-only, `mkdocs-material`); the "
        "markdown hub is the verified deliverable.",
        "- Screen-reader and POSIX-terminal validation remain UNVERIFIED on "
        "this host.",
        "",
        f"## Final status: **{status}**",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--forge", required=True)
    ap.add_argument("--inventory", type=Path,
                    default=Path("docs/knowledge-program"))
    args = ap.parse_args()
    repo = args.repo.resolve()
    out_dir = repo / args.inventory
    md = build_report(repo, args.forge, out_dir)
    out = out_dir / "final-report.md"
    out.write_text(md, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
