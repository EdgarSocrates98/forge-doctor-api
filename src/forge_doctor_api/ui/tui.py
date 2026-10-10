"""Full-screen TUI for this Forge — vendored canonical.

Each menu entry maps to the same real CLI argv the inline home menu
runs. Quick read-only commands are captured into the content pane;
long-running/interactive ones suspend the alt-screen and stream
attached. No fake buttons: every action is the real CLI.
"""

from __future__ import annotations

import subprocess
import sys

from forge_doctor_api.ui import home
from forge_doctor_api.ui.app import ActionData, Entry, ForgeApp, TextData
from forge_doctor_api.ui.kit import UIContext

# argv[0]s that stream progressively or open external surfaces —
# those run attached (alt-screen suspended) instead of captured.
_SUSPEND_VERBS = {"analyze", "judge", "collect", "migrate", "graph", "sdd"}


def _action_for(label: str, extra: list[str]) -> ActionData:
    suspend = bool(extra) and extra[0] in _SUSPEND_VERBS

    def _run() -> int:
        argv = home._cli_argv(list(extra))
        if argv is None:
            print(f"{home.CLI_NAME} not resolvable — run ./setup.sh")
            return 127
        print("$ " + " ".join(argv[:4]) + (" …" if len(argv) > 4 else ""))
        if suspend:
            return home._run_argv(argv)
        cp = subprocess.run(argv, capture_output=True, text=True,
                            timeout=300, check=False)
        sys.stdout.write(cp.stdout)
        if cp.stderr:
            sys.stdout.write("\n[stderr]\n" + cp.stderr)
        return cp.returncode

    return ActionData(callable=_run, title=f"{home.CLI_NAME} {' '.join(extra)}",
                      suspend=suspend)


def _wizard_entry() -> Entry:
    return Entry(label="installation wizard",
                 provider=lambda: ActionData(
                     callable=lambda: home._run_wizard(
                         UIContext.detect(force_plain=True)),
                     title="install wizard", suspend=True))


def entries() -> list[Entry]:
    out: list[Entry] = []
    for label, argv in home._MENU:
        if argv is None:
            continue  # quit lives in the app chrome (q)
        if argv == "__wizard__":
            out.append(_wizard_entry())
        else:
            out.append(Entry(label=label,
                             provider=lambda a=argv, lbl=label: _action_for(lbl, a)))
    return out


def run_tui(*, ctx: UIContext | None = None, version: str = "") -> int:
    ctx = ctx or UIContext.detect()
    return ForgeApp(ctx, forge_id=home.FORGE_NAME, title="command center",
                    entries=entries(), version=version).run()
