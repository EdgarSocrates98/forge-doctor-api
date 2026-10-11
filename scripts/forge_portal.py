#!/usr/bin/env python3
"""Forge Doctor API — optional local web portal (checkout-level).

Serves the Forge Portal on 127.0.0.1 with a session token: install
status, host detection, MCP verification, the real ``scan_project``
engine run and the service graph — the same truth the CLI/scripts
report. The portal is additive: every CLI verb, the MCP server and
``scripts/forge_install.py`` keep working with or without it.

This script is the *checkout-level* entrypoint for the portal — NOT a
``forge-doctor-api`` CLI verb, for the same reasons as
``forge_install.py``:

- The package boundary (``tests/test_boundary.py``) bans ``os``,
  ``subprocess``, ``shutil`` and network imports across ``src/`` — an
  HTTP server cannot live inside the package.
- The 0.2.0 RC window (``docs/rc-discipline.md``) forbids public-surface
  changes — CLI commands included — without a recorded exception.

Same contract as the in-package portals of sibling forges
(``forge/PortalApi/1``): loopback-only bind, 128-bit session token,
mutations behind explicit ``confirm`` + a signed plan token bound to
the echoed plan, named refusals for ambiguous intent, and no implicit
host launches (a browser has no TTY — launch returns the command to
copy). Assets are vendored under ``portal/assets`` by
``forge-portal/scripts/vendor.py``.

    python scripts/forge_portal.py [--root DIR] [--port N] [--no-browser]

stdlib-only + the installed ``forge_doctor_api`` package; mutates only
inside the resolved install target plus ``~/.forge/``. Exit code 0 on
clean shutdown, 1 on refusal (e.g. missing assets).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge_portal_adapter as pa


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="forge_portal.py",
        description="Serve the Forge Doctor API portal locally (127.0.0.1).",
    )
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="print the URL without opening the browser",
    )
    ap.add_argument("--port", type=int, default=0, help="port (0 = free port)")
    ap.add_argument("--root", default=None, help="workspace root (default: cwd)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path.cwd()
    adapter = pa.ForgeDoctorApiPortal(root)
    if adapter.assets_dir is None:
        print(
            json.dumps(
                {
                    "refusal": "FDA-PORTAL-NO-ASSETS",
                    "status": "refused",
                    "detail": (
                        "portal assets not vendored — run "
                        "`python scripts/vendor.py` in forge-portal"
                    ),
                },
                indent=2,
            )
        )
        return 1

    server = pa.fp.PortalServer(adapter, port=args.port, quiet=True)
    print(
        json.dumps(
            {
                "url": server.url,
                "note": "portal is optional — CLI/MCP keep working without it",
            }
        ),
        flush=True,
    )
    if not args.no_browser:
        import webbrowser

        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
