"""Normalized `--help` capture for CLI contract tests.

Rich reflows option tables to the terminal width — under CI's narrow
defaults an option name can fold onto a continuation line (or be
truncated), making substring assertions env-dependent. This helper pins
a wide, dumb terminal and strips ANSI so tests assert *content*, not
rendering.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from forge_doctor_api.cli import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_HELP_ENV = {
    "COLUMNS": "200",
    "TERM": "dumb",
    "NO_COLOR": "1",
}


def help_text(*argv: str) -> str:
    """Invoke `app argv --help`; return ANSI-free text at width 200."""
    result = CliRunner().invoke(
        app, [*argv, "--help"], env=_HELP_ENV, color=False)
    assert result.exit_code == 0, result.output
    return _ANSI_RE.sub("", result.output)


def assert_option(command: str, *argv: str, option: str) -> str:
    """Assert `option` is present in `command argv --help` output."""
    text = help_text(command, *argv)
    assert option in text, (
        f"{option!r} missing from `{command} --help` output")
    return text
