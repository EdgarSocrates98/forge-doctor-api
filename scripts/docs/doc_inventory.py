#!/usr/bin/env python3
"""Forge Documentation Standard v1 — command inventory extractor (Phase 0).

Walks the *real* CLI parser — never regex over source — and emits a
versioned inventory:

    python scripts/docs/doc_inventory.py \
        --forge spark-forge-aws --cli sparkforge-aws \
        --argparse sparkforge_aws.adapters.cli:build_parser \
        --out docs/reference/commands.generated.json

    python scripts/docs/doc_inventory.py \
        --forge api-forge --cli apiforge \
        --typer apiforge.cli:app \
        --out docs/reference/commands.generated.json

``--divergence docs/README.md docs/`` additionally scans markdown for
``<cli> <verb>`` mentions and reports documented-but-missing commands and
public commands no doc ever names.

stdlib-only; safe to vendor verbatim into any Forge repo.
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "forge/CommandInventory/v1"
TOOL = "doc_inventory.py/1"


def _resolve(spec: str) -> Any:
    mod, _, attr = spec.partition(":")
    return getattr(importlib.import_module(mod), attr)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# argparse walker
# --------------------------------------------------------------------------


def _argparse_args(parser: argparse.ArgumentParser) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for act in parser._actions:  # noqa: SLF001 — the parser IS the source
        if isinstance(act, argparse._SubParsersAction) or act is argparse._HelpAction:
            continue
        out.append(
            {
                "name": act.metavar or act.dest,
                "flags": list(act.option_strings),
                "required": bool(act.required),
                "default": None if act.default in (None, "==SUPPRESS==") else str(act.default),
                "choices": [str(c) for c in act.choices] if act.choices else None,
                "positional": not act.option_strings,
                "help": (act.help or "").strip() or None,
            }
        )
    return out


def walk_argparse(
    parser: argparse.ArgumentParser, prefix: str, out: list[dict[str, Any]]
) -> None:
    subs = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None  # noqa: SLF001
    )
    if subs is None:
        if prefix:
            out.append(
                {
                    "path": prefix,
                    "help": (parser.description or "").strip() or None,
                    "arguments": _argparse_args(parser),
                }
            )
        return
    if prefix:
        out.append(
            {
                "path": prefix,
                "help": (parser.description or "").strip() or None,
                "arguments": _argparse_args(parser),
                "group": True,
            }
        )
    for name, sub in subs.choices.items():
        if name in ("-h", "--help") or not isinstance(sub, argparse.ArgumentParser):
            continue
        walk_argparse(sub, f"{prefix} {name}".strip(), out)


# --------------------------------------------------------------------------
# click/typer walker
# --------------------------------------------------------------------------


def walk_click(cmd: Any, prefix: str, out: list[dict[str, Any]]) -> None:
    """Duck-typed walk — works for click AND typer≥0.20 (which no longer
    subclasses click.Group). Groups expose ``commands``; leaves expose
    ``params`` with ``param_type_name`` or click Option/Argument."""
    params: list[dict[str, Any]] = []
    for p in getattr(cmd, "params", []):
        ptype = getattr(p, "param_type_name", None)
        is_opt = ptype == "option" or bool(getattr(p, "opts", None))
        choices = getattr(getattr(p, "type", None), "choices", None)
        params.append(
            {
                "name": getattr(p, "name", None) or (getattr(p, "opts", None) or [None])[-1],
                "flags": list(getattr(p, "opts", []))
                + list(getattr(p, "secondary_opts", [])),
                "required": bool(getattr(p, "required", False)),
                "default": None if getattr(p, "default", None) is None else str(p.default),
                "choices": [str(c) for c in choices] if choices else None,
                "positional": not is_opt,
                "help": (getattr(p, "help", None) or "").strip() or None,
            }
        )
    entry: dict[str, Any] = {
        "path": prefix,
        "help": (getattr(cmd, "help", None) or "").strip() or None,
        "arguments": params,
    }
    subs = getattr(cmd, "commands", None)
    if subs:
        entry["group"] = True
        if prefix:
            out.append(entry)
        for name, sub in sorted(subs.items()):
            walk_click(sub, f"{prefix} {name}".strip(), out)
    elif prefix:
        out.append(entry)


# --------------------------------------------------------------------------
# divergence — documented-but-missing / public-but-undocumented
# --------------------------------------------------------------------------


def _doc_verbs(cli: str, md_files: list[Path]) -> tuple[set[str], dict[str, list[str]]]:
    """``<cli> <verb>`` tokens used in docs; returns (verbs, verb→files)."""
    pat = re.compile(rf"\b{re.escape(cli)}\s+([a-z][a-z0-9-]+)\b")
    verbs: set[str] = set()
    where: dict[str, list[str]] = {}
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pat.finditer(text):
            verbs.add(m.group(1))
            where.setdefault(m.group(1), []).append(str(f))
    return verbs, where


def divergence(
    cli: str, commands: list[dict[str, Any]], md_files: list[Path]
) -> dict[str, Any]:
    documented, where = _doc_verbs(cli, md_files)
    real_first = {c["path"].split()[0] for c in commands}
    missing = sorted(v for v in documented if v not in real_first)
    undocumented = sorted(
        v for v in real_first - {"-h", "help"} if v not in documented
    )
    rows = []
    for v in missing:
        rows.append(
            {
                "file": "; ".join(sorted(set(where[v]))),
                "line": "-",
                "problem": f"`{cli} {v}` documented but not a real command",
                "impact": "user runs a command that fails",
                "fix": f"remove or rename the `{v}` mention",
            }
        )
    return {
        "schema": "forge/DocDivergence/v1",
        "cli": cli,
        "documented_missing": rows,
        "undocumented_commands": undocumented,
        "generated_at": _utc_now(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forge", required=True)
    ap.add_argument("--cli", required=True)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--argparse", help="module:parser_factory callable")
    grp.add_argument("--typer", help="module:typer_app")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--divergence", type=Path, nargs="*", default=None,
                    help="markdown files/dirs to compare against")
    args = ap.parse_args()

    commands: list[dict[str, Any]] = []
    if args.argparse:
        factory = _resolve(args.argparse)
        parser = factory() if callable(factory) else factory
        walk_argparse(parser, "", commands)
    else:
        app = _resolve(args.typer)
        import typer.main

        walk_click(typer.main.get_command(app), "", commands)

    doc = {
        "schema": SCHEMA,
        "forge_id": args.forge,
        "cli": args.cli,
        "generated_at": _utc_now(),
        "generated_by": TOOL,
        "command_count": len(commands),
        "commands": commands,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), "utf-8")
    print(f"wrote {args.out} ({len(commands)} commands)")

    if args.divergence is not None:
        files: list[Path] = []
        for p in args.divergence:
            if p.is_dir():
                files += sorted(p.rglob("*.md"))
            elif p.is_file():
                files.append(p)
        div = divergence(args.cli, commands, files)
        out2 = args.out.with_name("divergence.generated.json")
        out2.write_text(json.dumps(div, indent=2, ensure_ascii=False), "utf-8")
        print(
            f"wrote {out2} "
            f"({len(div['documented_missing'])} doc-missing, "
            f"{len(div['undocumented_commands'])} undocumented)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
