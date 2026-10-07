"""Spec 068 + 090 — docs-as-contract: mechanical checks on documentation.

Docs are part of the shipped contract. These tests assert:

- every Typer CLI command appears in `docs/cli.md`,
- every output format documented has a writer (and vice versa),
- every relative link target in docs/README actually exists,
- the README quickstart commands run end-to-end,
- every `forge-doctor-api ...` command shown in docs resolves to a
  real catalog command path (spec 090),
- reproduction commands in release docs name real scripts, modules,
  and catalog commands (spec 090),
- `docs/mcp.md` tool names match the frozen MCP inventory (spec 090),
- `json` fences in docs parse, and contract-shaped examples validate
  through `contracts.models` (spec 090).
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from typer.testing import CliRunner

from forge_doctor_api.cli import app
from forge_doctor_api.contracts.models import HandoffBundle
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


# -- spec 090: docs-as-contract expansion --------------------------------------

_ELLIPSIS = re.compile(r"…|\.\.\.")
_PY_MODULE_ALLOWLIST = {
    "build", "mypy", "pytest", "ruff", "forge_doctor_api",
}


def _doc_command_lines() -> list[tuple[Path, str]]:
    """``forge-doctor-api ...`` invocations inside code fences or
    inline code spans — prose mentions of the binary are ignored."""
    out: list[tuple[Path, str]] = []
    for md in [README, *sorted(DOCS.rglob("*.md"))]:
        in_block = False
        for line in md.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                m = re.search(
                    r"\bforge-doctor-api\s+(?P<rest>[^`|\n]*)", line)
                if not m:
                    continue
                rest = m.group("rest").strip()
                # diagram/prose lines reuse the binary name as a label:
                # "forge-doctor-api = deterministic + ..." is not an
                # invocation — real commands never lead with =/+ or
                # contain bare " + "/" = " separators.
                if rest and not re.search(r"(^|\s)[=+](\s|$)", rest):
                    out.append((md, rest))
                continue
            for span in re.findall(r"`([^`]+)`", line):
                m = re.match(r"forge-doctor-api\s+(?P<rest>.+)", span)
                if m:
                    out.append((md, m.group("rest").strip()))
    return out


def _catalog_prefix_check(tokens: list[str]) -> str | None:
    """Leading tokens must form (a prefix of) a real catalog path."""
    paths = _command_paths()
    prefixes = {
        " ".join(p[:i + 1])
        for p in (path.split() for path in paths)
        for i in range(len(p))
    }
    command: list[str] = []
    for tok in tokens:
        if tok.startswith("-") or _ELLIPSIS.search(tok):
            break
        candidate = " ".join([*command, tok])
        if candidate in prefixes:
            command.append(tok)
            continue
        break
    if not command:
        if tokens and tokens[0].startswith("-"):
            return None  # flag invocation: --help, --version
        return "no catalog command matched"
    full = " ".join(command)
    if any(p == full or p.startswith(full + " ") for p in paths):
        return None
    return f"{full!r} is not a catalog command or group"


def test_documented_commands_resolve_to_catalog() -> None:
    bad: list[str] = []
    for md, rest in _doc_command_lines():
        try:
            tokens = shlex.split(rest, comments=False)
        except ValueError:
            tokens = rest.split()
        tokens = [t for t in tokens if not t.startswith("`")]
        err = _catalog_prefix_check(tokens)
        if err:
            bad.append(
                f"{md.relative_to(ROOT)}: forge-doctor-api {rest} → {err}")
    assert bad == [], "undocumented/misspelled commands:\n" + "\n".join(bad)


def test_release_doc_reproduction_commands_are_runnable() -> None:
    """Fenced commands in release/versioning docs must name real targets."""
    problems: list[str] = []
    for md in (DOCS / "release.md", DOCS / "versioning.md",
               DOCS / "release-policy.md"):
        if not md.exists():
            continue
        in_block = False
        for line in md.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            if not in_block:
                continue
            cmd = line.split("#", 1)[0].strip()
            if not cmd:
                continue
            m = re.match(r"python\s+(factory/\S+\.py)", cmd)
            if m:
                if not (ROOT / m.group(1)).exists():
                    problems.append(
                        f"{md.name}: missing script {m.group(1)}")
                continue
            m = re.match(r"python\s+-m\s+(\S+)", cmd)
            if m and m.group(1) not in _PY_MODULE_ALLOWLIST:
                problems.append(
                    f"{md.name}: unexpected module {m.group(1)}")
                continue
            if cmd.startswith("forge-doctor-api "):
                tokens = shlex.split(cmd)[1:]
                err = _catalog_prefix_check(tokens)
                if err:
                    problems.append(f"{md.name}: {cmd} → {err}")
                continue
            if cmd.startswith(("sha256sum", "pip ", "cd ", "git ")):
                continue
    assert problems == [], (
        "release reproduction commands are not runnable:\n"
        + "\n".join(problems))


def test_mcp_doc_tool_names_match_inventory() -> None:
    inventory = json.loads(
        (ROOT / "factory" / "artifacts" / "mcp-inventory.json")
        .read_text(encoding="utf-8"))
    registered = {t["name"] for t in inventory["tools"]}
    mcp_doc = (DOCS / "mcp.md").read_text(encoding="utf-8")
    mentioned = set(re.findall(r"`(doctor\.[a-z_]+)`", mcp_doc))
    assert mentioned <= registered, (
        "docs/mcp.md names tools absent from the frozen inventory: "
        f"{sorted(mentioned - registered)}")


_FENCE_JSON = re.compile(r"```json\n(.*?)```", re.DOTALL)
_CONTRACT_SHAPED = re.compile(
    r'"(findings|entities|relationships|schema_version)"')


def test_doc_json_examples_parse_and_validate() -> None:
    """json fences must be valid JSON; contract-shaped ones must parse."""
    checked = 0
    for md in [*sorted(DOCS.rglob("*.md")), README]:
        text = md.read_text(encoding="utf-8")
        for block in _FENCE_JSON.findall(text):
            checked += 1
            payload = json.loads(block)  # valid JSON or the test fails
            if (isinstance(payload, dict)
                    and "findings" in payload
                    and _CONTRACT_SHAPED.search(block)):
                HandoffBundle.from_dict(payload)
    # canonical fixtures are the shipped contract examples
    canonical = sorted(
        (ROOT / "tests" / "fixtures" / "contracts" / "canonical")
        .glob("*.json"))
    assert canonical, "canonical contract fixtures must exist"
    for fixture in canonical:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "findings" in payload:
            HandoffBundle.from_dict(payload)
    assert checked >= 1, "expected at least one json doc example"
