"""Regenerate golden CLI help snapshots — deterministic, offline.

Run after an intentional CLI contract change:

    python tests/golden/_regen.py

The diff on tests/golden/cli/*.txt *is* the contract change — review it
like a schema diff.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cli_help import normalized_help
from forge_doctor_api.cli.catalog import command_inventory

OUT_DIR = Path(__file__).resolve().parent / "cli"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for entry in command_inventory():
        name = entry.path.replace(" ", "-") + ".txt"
        (OUT_DIR / name).write_text(
            normalized_help(*entry.path.split()), encoding="utf-8")
        print(f"wrote {OUT_DIR / name}")


if __name__ == "__main__":
    main()
