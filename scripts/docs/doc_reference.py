"""doc_reference.py — render docs/reference/commands.md from commands.generated.json.

Canonical Forge Documentation & CLI Experience Standard v1 §4:
every public command gets what-it-does (help text), syntax, an arguments
table, defaults, and a hand-editable "notes" block the generator never
overwrites (``<!-- keep:start -->`` .. ``<!-- keep:end -->``).

stdlib-only; runnable from any repo root:

    python doc_reference.py --inventory docs/reference/commands.generated.json \
        --out docs/reference/commands.md --cli theforge
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

KEEP_START = "<!-- keep:start -->"
KEEP_END = "<!-- keep:end -->"


def _syntax(cli: str, cmd: dict) -> str:
    parts = [cli, *cmd["path"].split()]
    for opt in cmd.get("options", []):
        flag = opt["flags"][0] if opt["flags"] else opt["name"]
        val = "" if opt.get("flag") else " <" + opt["name"].lower().replace("_", "-") + ">"
        shown = flag + val
        parts.append(shown if opt.get("required") else f"[{shown}]")
    for arg in cmd.get("arguments", []):
        parts.append(f"<{arg['name']}>" if arg.get("required", True) else f"[{arg['name']}]")
    return " ".join(parts)


def _args_table(cmd: dict) -> list[str]:
    rows = ["| argument/flag | required | default | description |", "|---|---|---|---|"]
    for arg in cmd.get("arguments", []):
        rows.append(
            f"| `{arg['name']}` | {'yes' if arg.get('required', True) else 'no'} | — |"
            f" {arg.get('help') or '—'} |"
        )
    for opt in cmd.get("options", []):
        flags = "`, `".join(opt["flags"])
        default = opt.get("default")
        default = "—" if default in (None, False, "") else f"`{default}`"
        if opt.get("flag"):
            default = "off"
        choices = opt.get("choices")
        desc = opt.get("help") or "—"
        if choices:
            desc += f" (one of: {', '.join(str(c) for c in choices)})"
        rows.append(f"| `{flags}` | {'yes' if opt.get('required') else 'no'} | {default} | {desc} |")
    return rows


def _extract_keeps(existing: str) -> dict[str, str]:
    """Preserve hand-written keep-blocks keyed by command anchor."""
    keeps: dict[str, str] = {}
    for m in re.finditer(
        r"(## `([^`]+)`.*?)" + re.escape(KEEP_START) + r"(.*?)" + re.escape(KEEP_END),
        existing,
        re.DOTALL,
    ):
        keeps[m.group(2)] = m.group(3)
    return keeps


def render(inv: dict, cli: str, existing: str | None) -> str:
    keeps = _extract_keeps(existing or "")
    out = [
        f"# `{cli}` command reference",
        "",
        "Generated from the real CLI parser by `doc_inventory.py` +"
        " `doc_reference.py`. Do not hand-edit generated sections — write"
        " between `keep:start`/`keep:end` markers. Status vocabulary:"
        " `available` unless marked otherwise.",
        "",
    ]
    groups: dict[str, list[dict]] = {}
    for cmd in inv["commands"]:
        top = cmd["path"].split()[0]
        groups.setdefault(top, []).append(cmd)
    out.append("## Groups")
    out.append("")
    for top in sorted(groups):
        out.append(f"- [`{top}`](#{top}) — {len(groups[top])} command(s)")
    out.append("")
    for top in sorted(groups):
        out.append(f"## {top}")
        out.append("")
        for cmd in sorted(groups[top], key=lambda c: c["path"]):
            path = cmd["path"]
            out.append(f"### `{path}`")
            out.append("")
            if cmd.get("help"):
                out.append(cmd["help"].strip())
                out.append("")
            out.append("**Syntax**")
            out.append("")
            out.append(f"```text\n{_syntax(cli, cmd)}\n```")
            out.append("")
            if cmd.get("options") or cmd.get("arguments"):
                out += _args_table(cmd)
                out.append("")
            out.append(KEEP_START)
            out.append(keeps.get(path, "").strip() or
                       "_free notes — errors, examples, next steps (hand-written, preserved)_")
            out.append(KEEP_END)
            out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cli", required=True)
    a = ap.parse_args()
    inv = json.loads(Path(a.inventory).read_text(encoding="utf-8"))
    out_path = Path(a.out)
    existing = out_path.read_text(encoding="utf-8") if out_path.exists() else None
    text = render(inv, a.cli, existing)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path} ({len(inv['commands'])} commands)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
