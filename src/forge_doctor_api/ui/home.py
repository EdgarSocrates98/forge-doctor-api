"""forge-doctor-api interactive home — bare CLI on a TTY.

Menu entries run the forge's *real* CLI argv in a subprocess (installed
launcher, else the agentic manifest's ``cli_entry`` via the checkout) —
the TUI is a shell over the real surface, never a second engine.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from forge_doctor_api.ui.i18n import t
from forge_doctor_api.ui.kit import NonInteractive, UIContext, _c, dashboard, select

FORGE_NAME = 'forge-doctor-api'
CLI_NAME = 'forge-doctor-api'
CLI_ENTRY = 'forge_doctor_api.cli:main'

_MENU: list[tuple[str, list[str] | None]] = [
    ('Scan this project', ['scan']),
    ('Diagnose', ['diagnose']),
    ('Fingerprint APIs', ['fingerprint']),

        'Graph Studio (browser)', ['graph','.','--ui'],
    ("installation wizard", "__wizard__"),
    ("quit", None),
]


def _cli_argv(extra: list[str]) -> list[str] | None:
    """Resolve the real CLI argv: installed launcher else checkout entry."""
    exe = shutil.which(CLI_NAME)
    if exe:
        return [exe, *extra]
    if CLI_ENTRY:
        module, _, fn = CLI_ENTRY.partition(":")
        checkout = next(
            (a for a in Path(__file__).resolve().parents if (a / "forge.json").is_file()),
            None,
        )
        if checkout is None:
            return None
        code = (
            f"import sys; sys.path.insert(0, {str(checkout)!r});"
            f" sys.path.insert(0, {str(checkout / 'src')!r});"
            f" from {module} import {fn} as _m; _m()"
        ).format(checkout=checkout, module=module, fn=fn)
        return [sys.executable, "-c", code, *extra]
    return None


def _run_argv(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, check=False).returncode
    except FileNotFoundError:
        return 127


def run_home(*, ctx: UIContext | None = None) -> int:
    ctx = ctx or UIContext.detect()
    if not ctx.interactive:
        raise NonInteractive("home requires a TTY")
    dashboard(
        f"{FORGE_NAME}  workspace: {Path.cwd().name}",
        [("CLI", [("command", CLI_NAME), ("entry", CLI_ENTRY or "-")])],
        ctx=ctx,
    )

    while True:
        idx = select(t("choose", ctx.language), [label for label, _ in _MENU], ctx=ctx)
        if idx is None:
            return 0
        _label, argv = _MENU[idx]
        if argv is None:
            return 0
        print()
        if argv == "__wizard__":
            _run_wizard(ctx)
            print()
            continue
        resolved = _cli_argv(list(argv))
        if resolved is None:
            print(_c(ctx, "31", "  " + CLI_NAME + " not resolvable — run ./setup.sh"))
        else:
            print(_c(ctx, "2", "  $ " + " ".join(resolved[:3]) + " …"))
            rc = _run_argv(resolved)
            print(_c(ctx, "32" if rc == 0 else "31", f"  exit {rc}"))
        print()


def _script_root() -> Path:
    return next(
        a for a in Path(__file__).resolve().parents if (a / "scripts" / "forge_install.py").is_file()
    )


def _script_call(op: str, **kw) -> dict:
    """Call the real ``scripts/forge_install.py`` and parse its JSON receipt."""
    argv = [sys.executable, str(_script_root() / "scripts" / "forge_install.py"), op]
    for key in ("scope", "host", "profile"):
        if kw.get(key) is not None:
            argv += [f"--{key}", str(kw[key])]
    if kw.get("components"):
        comps = kw["components"]
        argv += ["--components", ",".join(comps) if not isinstance(comps, str) else comps]
    if kw.get("dry_run"):
        argv.append("--dry-run")
    if kw.get("yes"):
        argv.append("--yes")
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "completed" if proc.returncode == 0 else "failed",
                "checks": [], "stderr_tail": proc.stderr[-400:]}


def _run_wizard(ctx: UIContext) -> None:
    from forge_doctor_api.ui.wizard import run_wizard

    run_wizard(
        forge_name=FORGE_NAME,
        install_fn=lambda **kw: _script_call("install", **kw),
        doctor_fn=lambda **kw: _script_call("doctor", **kw),
        ctx=ctx,
    )
