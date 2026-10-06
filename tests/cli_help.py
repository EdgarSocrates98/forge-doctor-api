"""Normalized `--help` capture for CLI contract tests.

Rich reflows option tables to the terminal width — under CI's narrow
defaults an option name can fold onto a continuation line (or be
truncated), making substring assertions env-dependent. This helper pins
a wide, dumb terminal and strips ANSI so tests assert *content*, not
rendering.
"""

from __future__ import annotations

import re
import textwrap

import typer.rich_utils
from typer.testing import CliRunner

from forge_doctor_api.cli import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_HELP_ENV = {
    "COLUMNS": "200",
    "TERM": "dumb",
    "NO_COLOR": "1",
}

# typer reads TERMINAL_WIDTH once at import into MAX_WIDTH; patching the
# module attribute is the only in-process way to pin render width —
# COLUMNS alone is not honored on every platform's auto-detect path.
_PINNED_WIDTH = 200


def help_text(*argv: str) -> str:
    """Invoke `app argv --help`; return ANSI-free text at a pinned width."""
    previous = typer.rich_utils.MAX_WIDTH
    typer.rich_utils.MAX_WIDTH = _PINNED_WIDTH
    try:
        result = CliRunner().invoke(
            app, [*argv, "--help"], env=_HELP_ENV, color=False)
    finally:
        typer.rich_utils.MAX_WIDTH = previous
    assert result.exit_code == 0, result.output
    return _ANSI_RE.sub("", result.output)


# Rich picks a box style per platform (rounded/heavy/double under
# UTF-8 terminals, square under legacy Windows) and wraps at whatever
# width its detection path reports — COLUMNS/pinning is not honored
# identically on every platform. So the canonical form must be
# width-invariant: strip every decoration glyph, collapse to a token
# stream, re-wrap at a fixed 100 columns. Snapshots pin the contract
# (content + order), never the renderer's layout.
_BOX_GLYPHS = (
    "─━═│┃║╌╍┄┅┈┉"
    "┌┐└┘┏┓┗┛╔╗╚╝╭╮╰╯"
    "├┤┬┴┼┣┫┳┻╋╠╣╦╩╬╞╡╤╧╪"
)


def normalized_help(*argv: str) -> str:
    """`help_text` reduced to its token stream, re-wrapped at 100 cols.

    Box borders, rules, padding and line-wrap positions are renderer
    details; the snapshot asserts option names, argument names, help
    text and their order — identical bytes on any platform/terminal.
    """
    tokens: list[str] = []
    for raw in help_text(*argv).splitlines():
        line = raw.strip(_BOX_GLYPHS + " \t")
        if not line:
            continue
        tokens.extend(line.split())
    return "\n".join(textwrap.wrap(" ".join(tokens), 100)) + "\n"


def assert_option(command: str, *argv: str, option: str) -> str:
    """Assert `option` is present in `command argv --help` output."""
    text = help_text(command, *argv)
    assert option in text, (
        f"{option!r} missing from `{command} --help` output")
    return text
