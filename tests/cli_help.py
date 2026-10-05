"""Normalized `--help` capture for CLI contract tests.

Rich reflows option tables to the terminal width — under CI's narrow
defaults an option name can fold onto a continuation line (or be
truncated), making substring assertions env-dependent. This helper pins
a wide, dumb terminal and strips ANSI so tests assert *content*, not
rendering.
"""

from __future__ import annotations

import re

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
# UTF-8 terminals, square under legacy Windows). Snapshots pin the
# square set — map every variant onto it so the *box flavor* is never
# part of the contract.
_BOX_CANON = str.maketrans({
    "╭": "┌", "╮": "┐", "╰": "└", "╯": "┘",
    "┏": "┌", "┓": "┐", "┗": "└", "┛": "┘",
    "╔": "┌", "╗": "┐", "╚": "└", "╝": "┘",
    "━": "─", "═": "─", "┃": "│", "║": "│",
    "┣": "├", "┫": "┤", "┳": "┬", "┻": "┴", "╋": "┼",
    "╠": "├", "╣": "┤", "╦": "┬", "╩": "┴", "╬": "┼",
    "╞": "├", "╡": "┤", "╤": "┬", "╧": "┴", "╪": "┼",
})

_DECORATIVE_RE = re.compile(r"^[\s─═━═╌╍┄┅┈┉\-_=~*#|+.·:<>]*$")
_EDGE_GLYPHS = "│┃| "
_WS_RUN_RE = re.compile(r"\s{2,}")


def normalized_help(*argv: str) -> str:
    """`help_text` canonicalized to content: ANSI stripped, box-drawing
    variants folded to the square set, decoration-only lines dropped,
    edge glyphs and intra-line column padding collapsed — snapshots pin
    the contract, not the renderer's layout or platform box style."""
    lines: list[str] = []
    blank = False
    for raw in help_text(*argv).splitlines():
        line = raw.rstrip().translate(_BOX_CANON)
        if _DECORATIVE_RE.match(line):
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        line = _WS_RUN_RE.sub(" ", line.strip(_EDGE_GLYPHS))
        lines.append(line)
        blank = False
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def assert_option(command: str, *argv: str, option: str) -> str:
    """Assert `option` is present in `command argv --help` output."""
    text = help_text(command, *argv)
    assert option in text, (
        f"{option!r} missing from `{command} --help` output")
    return text
