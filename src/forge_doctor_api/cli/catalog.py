"""Machine-readable CLI contract: command inventory + stability levels.

`command_inventory()` walks the Typer tree via Click and returns every
public command path with its declared options and arguments — the drift
tests and docs-as-contract checks assert against this surface, so the
docs and the binary cannot diverge silently.

Every command has a declared stability level; an unregistered command
in the inventory resolves to EXPERIMENTAL so new commands must opt into
STABLE deliberately.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import click
import typer.main

from forge_doctor_api.cli import app


class CommandStability(enum.Enum):
    """Public-contract stability level for a CLI command."""

    STABLE = "stable"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"


# Declared stability per command path. Anything missing here resolves
# to EXPERIMENTAL — promotions to STABLE are deliberate, reviewed acts.
STABILITY: dict[str, CommandStability] = {
    "scan": CommandStability.STABLE,
    "inventory": CommandStability.STABLE,
    "diff": CommandStability.STABLE,
    "fingerprint": CommandStability.STABLE,
    "graph": CommandStability.STABLE,
    "blast-radius": CommandStability.STABLE,
    "diagnose": CommandStability.STABLE,
    "explain": CommandStability.STABLE,
    "lab": CommandStability.STABLE,
    "mcp": CommandStability.EXPERIMENTAL,
    "contract inspect": CommandStability.STABLE,
    "contract diff": CommandStability.STABLE,
    "contract compatibility": CommandStability.STABLE,
    "runtime requests": CommandStability.STABLE,
    "runtime baseline": CommandStability.STABLE,
    "runtime regressions": CommandStability.STABLE,
    "security inspect": CommandStability.STABLE,
    "reliability inspect": CommandStability.STABLE,
    "reliability path": CommandStability.STABLE,
    "snapshot save": CommandStability.EXPERIMENTAL,
    "snapshot list": CommandStability.EXPERIMENTAL,
    "snapshot diff": CommandStability.EXPERIMENTAL,
    "snapshot regressions": CommandStability.EXPERIMENTAL,
    "knowledge list": CommandStability.EXPERIMENTAL,
    "knowledge validate": CommandStability.EXPERIMENTAL,
    "plugins list": CommandStability.EXPERIMENTAL,
    "plugins inspect": CommandStability.EXPERIMENTAL,
    "plugins verify": CommandStability.EXPERIMENTAL,
}


@dataclass(frozen=True, kw_only=True)
class CommandEntry:
    """One public command's declared surface."""

    path: str  # space-joined command path, e.g. "contract inspect"
    options: tuple[str, ...] = ()  # long flags, sorted ("--semantic")
    arguments: tuple[str, ...] = ()  # positional names, in order
    stability: CommandStability = CommandStability.EXPERIMENTAL


def stability_of(path: str) -> CommandStability:
    """Registry lookup — unlisted commands are EXPERIMENTAL."""
    return STABILITY.get(path, CommandStability.EXPERIMENTAL)


def _options(cmd: click.Command) -> tuple[str, ...]:
    """Long flags on the command. Duck-typed: typer 0.27 params are not
    `click.Option` subclasses, so classify by the declared flag names."""
    flags: set[str] = set()
    for param in cmd.params:
        for opt in (
            *getattr(param, "opts", ()),
            *getattr(param, "secondary_opts", ()),
        ):
            if opt.startswith("--") and opt != "--help":
                flags.add(opt)
    return tuple(sorted(flags))


def _arguments(cmd: click.Command) -> tuple[str, ...]:
    """Positional params — declared names with no `-`-prefixed flag."""
    return tuple(
        str(param.name)
        for param in cmd.params
        if not any(o.startswith("-") for o in getattr(param, "opts", ()))
        and getattr(param, "name", None)
    )


def command_inventory() -> tuple[CommandEntry, ...]:
    """Every public `forge-doctor-api` command — sorted, deterministic."""
    root = typer.main.get_command(app)
    entries: list[CommandEntry] = []

    def walk(group: object, prefix: str = "") -> None:
        commands = getattr(group, "commands", {})
        for name in sorted(commands):
            cmd = commands[name]
            path = f"{prefix}{name}".strip()
            if hasattr(cmd, "commands"):
                walk(cmd, f"{path} ")
            else:
                entries.append(CommandEntry(
                    path=path,
                    options=_options(cmd),
                    arguments=_arguments(cmd),
                    stability=stability_of(path),
                ))

    walk(root)
    return tuple(entries)


def command_paths() -> tuple[str, ...]:
    """Just the paths — for docs-presence checks."""
    return tuple(e.path for e in command_inventory())
