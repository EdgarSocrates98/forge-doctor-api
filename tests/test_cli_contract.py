"""Spec 072 — CLI/docs contract stability.

`docs/cli.md` is part of the public contract: every declared option on
a command must be documented, every documented option must exist, and
each command's stability level is rendered next to its section.

Golden help snapshots under `tests/golden/cli/` pin the *content* of
`--help` (ANSI-free, width-normalized, decoration-stripped) so renderer
version drift cannot silently change the published surface. Regenerate
with `python tests/golden/_regen.py` after an intentional change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cli_help import normalized_help
from forge_doctor_api.cli.catalog import (
    CommandStability,
    command_inventory,
    stability_of,
)

ROOT = Path(__file__).resolve().parents[1]
CLI_MD = ROOT / "docs" / "cli.md"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden" / "cli"

_OPTION_RE = re.compile(r"(?<!\w)--[a-z][a-z0-9-]*")


def _doc_sections() -> dict[str, str]:
    """`## heading` -> section body text."""
    sections: dict[str, list[str]] = {}
    current = "_header"
    for line in CLI_MD.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _section_for(path: str) -> str:
    """Longest `##` heading that prefixes the command path."""
    sections = _doc_sections()
    tokens = path.split()
    for depth in range(len(tokens), 0, -1):
        heading = " ".join(tokens[:depth])
        if heading in sections:
            return sections[heading]
    return ""


def test_inventory_covers_registry_and_vice_versa() -> None:
    paths = {e.path for e in command_inventory()}
    from forge_doctor_api.cli.catalog import STABILITY

    registered = set(STABILITY)
    assert registered - paths == set(), (
        f"registry entries with no command: {sorted(registered - paths)}")
    unregistered = paths - registered
    assert unregistered == set(), (
        f"commands without a declared stability level: "
        f"{sorted(unregistered)}")


def test_every_command_documented() -> None:
    text = CLI_MD.read_text(encoding="utf-8")
    missing = [e.path for e in command_inventory() if e.path not in text]
    assert missing == [], f"commands missing from docs/cli.md: {missing}"


def test_documented_options_exist() -> None:
    """Every `--flag` named under a section must belong to a command
    that section documents."""
    sections = _doc_sections()
    inventory = command_inventory()

    def heading_cmds(heading: str) -> set[str]:
        names = {
            e.path for e in inventory
            if e.path == heading or e.path.startswith(heading + " ")
        }
        opts: set[str] = set()
        for e in inventory:
            if e.path in names:
                opts.update(e.options)
        return opts

    bad: list[str] = []
    for heading, body in sections.items():
        if heading == "_header":
            continue
        documented = set(_OPTION_RE.findall(body))
        real = heading_cmds(heading)
        for opt in sorted(documented - real):
            bad.append(f"{heading}: {opt} documented but not a real option")
    assert bad == [], "documented options missing from CLI:\n" + "\n".join(
        bad)


def test_stable_command_options_documented() -> None:
    bad: list[str] = []
    for entry in command_inventory():
        if entry.stability is not CommandStability.STABLE:
            continue
        section = _section_for(entry.path)
        for opt in entry.options:
            if opt not in section:
                bad.append(f"{entry.path}: {opt} undocumented")
    assert bad == [], "STABLE options missing from docs:\n" + "\n".join(bad)


def test_stability_levels_rendered_in_docs() -> None:
    sections = _doc_sections()
    bad: list[str] = []
    for entry in command_inventory():
        tokens = entry.path.split()
        heading = next(
            (" ".join(tokens[:d]) for d in range(len(tokens), 0, -1)
             if " ".join(tokens[:d]) in sections),
            None,
        )
        if heading is None:
            bad.append(f"{entry.path}: no docs section")
            continue
        if entry.stability.value not in sections[heading]:
            bad.append(f"{heading}: stability {entry.stability.value} "
                       "not rendered")
    assert bad == [], "sections missing stability markers:\n" + "\n".join(bad)


def test_public_options_pinned() -> None:
    """Spec 072 anchors: `diff --semantic` and `diagnose --before` are
    part of the public contract."""
    inventory = {e.path: e for e in command_inventory()}
    assert "--semantic" in inventory["diff"].options
    assert "--before" in inventory["diagnose"].options
    assert stability_of("diff") is CommandStability.STABLE
    assert stability_of("diagnose") is CommandStability.STABLE


@pytest.mark.parametrize(
    "entry",
    list(command_inventory()),
    ids=[e.path for e in command_inventory()],
)
def test_help_golden_snapshot(entry) -> None:
    golden = GOLDEN_DIR / (entry.path.replace(" ", "-") + ".txt")
    actual = normalized_help(*entry.path.split())
    if not golden.exists():
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8")
        pytest.fail(
            f"missing golden snapshot created: {golden.name} — "
            "review and commit it")
    expected = golden.read_text(encoding="utf-8")
    assert actual == expected, (
        f"`{entry.path} --help` drifted from golden snapshot; "
        "if intentional, run `python tests/golden/_regen.py` and review "
        "the diff")
