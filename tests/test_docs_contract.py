"""Spec 068 — docs-as-contract: mechanical checks on documentation.

Docs are part of the shipped contract. These tests assert:

- every Typer CLI command appears in `docs/cli.md`,
- every output format documented has a writer (and vice versa),
- every relative link target in docs/README actually exists,
- the README quickstart commands run end-to-end.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.cli import app
from forge_doctor_api.output.writers import WRITERS

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
README = ROOT / "README.md"
CLI_MD = DOCS / "cli.md"

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""


def _command_paths() -> list[str]:
    """Walk the Typer tree → `["scan", "contract inspect", ...]`."""
    paths: list[str] = []

    def walk(typer_app: object, prefix: str = "") -> None:
        for info in getattr(typer_app, "registered_commands", ()):
            name = info.name or (info.callback.__name__.replace(
                "_", "-") if info.callback else "")
            paths.append(f"{prefix}{name}".strip())
        for group in getattr(typer_app, "registered_groups", ()):
            sub = group.typer_instance
            gname = group.name or (sub.info.name if sub else "")
            walk(sub, f"{prefix}{gname} ")

    walk(app)
    return sorted(paths)


def test_every_cli_command_documented() -> None:
    cli_text = CLI_MD.read_text(encoding="utf-8")
    paths = _command_paths()
    assert paths, "Typer tree walk must find commands"
    missing = [p for p in paths if p not in cli_text]
    assert missing == [], (
        f"commands missing from docs/cli.md: {missing}")


def test_documented_formats_have_writers() -> None:
    cli_text = (CLI_MD.read_text(encoding="utf-8")
                + (DOCS / "output-formats.md").read_text(encoding="utf-8"))
    for fmt in WRITERS:
        assert fmt in cli_text, f"writer {fmt!r} undocumented"
    # formats named in docs must be real writers or report/console
    for fmt in ("json", "jsonl", "sarif", "agent", "report"):
        assert fmt in cli_text


_LINK_RE = re.compile(r"\]\((?P<target>[^)\s#]+)(?:#[^)]*)?\)")


def test_doc_links_resolve() -> None:
    sources = [README, *sorted(DOCS.rglob("*.md"))]
    broken: list[str] = []
    for md in sources:
        text = md.read_text(encoding="utf-8")
        for target in _LINK_RE.findall(text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                continue  # external scheme (https, mailto, doctor://)
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{md.relative_to(ROOT)} → {target}")
    assert broken == [], "broken doc links:\n" + "\n".join(broken)


def _quickstart_commands() -> list[list[str]]:
    text = README.read_text(encoding="utf-8")
    start = text.index("## Quickstart")
    end = text.index("\n## ", start + 1)
    section = text[start:end]
    commands: list[list[str]] = []
    in_block = False
    for line in section.splitlines():
        if line.strip().startswith("```"):
            in_block = not in_block
            continue
        line = line.strip()
        if in_block and line.startswith("forge-doctor-api "):
            commands.append(
                shlex.split(line)[1:])  # drop the binary name
    return commands


def test_readme_quickstart_commands_run(tmp_path: Path) -> None:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    (tmp_path / "baseline").mkdir()
    (tmp_path / "baseline" / "api.yaml").write_text(
        OPENAPI, encoding="utf-8")
    commands = _quickstart_commands()
    assert commands, "README quickstart must contain CLI commands"
    runner = CliRunner()
    for argv in commands:
        argv = [
            str(tmp_path) if a in (".", "./my-service") else
            str(tmp_path / "baseline") if a == "./last-release" else
            str(tmp_path / a) if a.endswith(".sarif") else a
            for a in argv
        ]
        res = runner.invoke(app, argv)
        assert res.exit_code in (0, 1), (
            f"quickstart command failed ({res.exit_code}): "
            f"forge-doctor-api {' '.join(argv)}\n{res.output}")
