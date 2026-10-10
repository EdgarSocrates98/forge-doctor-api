#!/usr/bin/env python3
"""Forge Doctor API — portable install lifecycle (forge/* contract v1).

This script is the *checkout-level* adapter for the portable installation
contract. It is deliberately NOT a ``forge-doctor-api`` CLI verb:

- The package boundary (``tests/test_boundary.py``) bans ``os``,
  ``subprocess`` and ``shutil`` imports across ``src/`` — the install
  engine cannot live inside the package.
- The 0.2.0 RC window (``docs/rc-discipline.md``) forbids public-surface
  changes — CLI commands included — without a recorded exception.

Same verbs, same receipts, same ledger as the in-package adapters shipped
by sibling forges; only the entrypoint differs:

    python scripts/forge_install.py install [--scope S] [--host H]
        [--profile P] [--root DIR] [--yes|--dry-run]
    python scripts/forge_install.py status|doctor|repair
        [--scope S] [--root DIR] [--dry-run]
    python scripts/forge_install.py uninstall [--scope S] [--root DIR]
        [--purge] [--dry-run]
    python scripts/forge_install.py update [--to VER] [--repo DIR] [--dry-run]
    python scripts/forge_install.py mcp-verify

stdlib-only; mutates only inside the resolved install target plus
``~/.forge/``. Exit code 0 for PASS/planned/completed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_installkit as kit

REPO = Path(__file__).resolve().parents[1]

try:  # version comes from the installed dist or the source tree
    from importlib.metadata import version as _dv
    _VERSION = _dv("forge-doctor-api")
except Exception:  # checkout without install — read pyproject
    try:
        import tomllib
        _VERSION = tomllib.loads(
            (REPO / "pyproject.toml").read_bytes().decode())[
                "project"]["version"]
    except Exception:
        _VERSION = "0.0.0+unknown"

FORGE_ID = "forge-doctor-api"
STATE_DIR = ".forge-doctor-api/install"
PROFILES = ("minimal", "recommended", "full")
SCOPES = ("project", "workspace", "user")
HOSTS = ("claude", "devin", "codex", "copilot")


def _spec() -> kit.ForgeSpec:
    return kit.ForgeSpec(
        forge_id=FORGE_ID,
        package="forge_doctor_api",
        distribution="forge-doctor-api",
        cli_name="forge-doctor-api",
        python_spec=">=3.11",
        state_dir=STATE_DIR,
        mcp_command=("forge-doctor-api", "mcp"),
        mcp_server_name="forge-doctor-api",
        mcp_verify_tool="doctor.get_reliability",
        version_cmd=("--version",),
        render_assets=lambda ctx: {},  # no host mirrors published
        marker_files=("AGENTS.md", "CLAUDE.md"),
        marker_body=(
            "**Forge Doctor API** is installed in this project.\n\n"
            "- MCP server: `forge-doctor-api` (managed key in `.mcp.json`)\n"
            "- Lifecycle: `python scripts/forge_install.py "
            "status|doctor|repair|uninstall` from the checkout\n\n"
            "Content between the `forge-doctor-api:managed` markers is "
            "managed; content outside belongs to the user."
        ),
        user_state_dir="~/.forge-doctor-api",
        spawn_ok=True,  # scripts/ is outside the src/ boundary
    )


def _ctx(args: argparse.Namespace, hosts: tuple[str, ...]) -> kit.InstallContext:
    spec = _spec()
    target = kit.resolve_scope(spec, args.scope, Path.cwd(),
                               Path(args.root) if args.root else None)
    return kit.InstallContext(
        spec=spec, scope=args.scope, root=target,
        state_dir=kit.state_dir_for(spec, args.scope, target),
        profile=getattr(args, "profile", "recommended"),
        hosts=hosts, dry_run=getattr(args, "dry_run", False),
        options=kit.component_options(
            getattr(args, "profile", "recommended"),
            tuple(c.strip() for c in args.components.split(",") if c.strip())
            if getattr(args, "components", None) else None,
        ))


def _hosts(host: str) -> tuple[str, ...]:
    """``all`` → todos; ``none``/vazio → opt-out explícito (nunca todos);
    nome único ou csv → subconjunto validado (GAP-003)."""
    if host == "all":
        return HOSTS
    if not host or host == "none":
        return ()
    nomes = [h.strip() for h in host.split(",") if h.strip()]
    desconhecidos = [h for h in nomes if h not in HOSTS]
    if desconhecidos:
        raise kit.InstallError(
            kit.E_HOST, f"host {desconhecidos[0]!r}; {list(HOSTS)}+all,none")
    return tuple(dict.fromkeys(nomes))


def _emit(doc: Any) -> None:
    print(json.dumps(doc, indent=2))


def _register(ctx: kit.InstallContext) -> None:
    path = kit.installations_dir() / f"{FORGE_ID}.json"
    existing = kit._load_json(path, None)
    doc: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    doc.update({
        "schema": kit.SCHEMA_MANIFEST, "forge_id": FORGE_ID,
        "package": "forge_doctor_api", "distribution": FORGE_ID,
        "cli": {"name": "forge-doctor-api",
                "version_cmd": ["forge-doctor-api", "--version"]},
        "version": _VERSION,
        "updated_at": kit._utc_now(),
        "installed_at": doc.get("installed_at", kit._utc_now()),
        "installed_by": doc.get("installed_by",
                                {"agent": "forge_install.py",
                                 "version": _VERSION}),
        "source": doc.get("source", {"kind": "project-install",
                                     "path": str(ctx.root)}),
    })
    doc.setdefault("install_root", str(kit.installs_root() / FORGE_ID))
    doc.setdefault("mcp", {"server_name": FORGE_ID,
                           "command": ["forge-doctor-api", "mcp"],
                           "verified": False})
    kit.register_installation(doc)


def _installation_manifest() -> dict[str, Any]:
    doc = kit._load_json(kit.installations_dir() / f"{FORGE_ID}.json", None)
    return doc if isinstance(doc, dict) else {}


def _receipt(operation: str, checks: list[dict[str, Any]],
             status: str) -> dict[str, Any]:
    return {
        "schema": kit.SCHEMA_RECEIPT, "forge_id": FORGE_ID,
        "operation": operation, "managed_files": [], "checks": checks,
        "verification": {"status": "PASS" if all(
            c["status"] in ("PASS", "NOT_APPLICABLE", "UNVERIFIED")
            for c in checks) else "FAIL"},
        "status": status, "created_at": kit._utc_now(),
        "created_by": f"{FORGE_ID}/{_VERSION}",
    }


def cmd_install(a: argparse.Namespace) -> int:
    if a.profile not in PROFILES:
        raise kit.InstallError(kit.E_PROFILE, f"profile {a.profile!r}")
    ctx = _ctx(a, _hosts(a.host))
    with kit.acquire_lock(ctx.state_dir):
        receipt = kit.apply_install(ctx, approved=a.yes)
    if not a.dry_run and receipt.get("status") == "completed":
        kit._write_receipt(ctx.state_dir, receipt)
        _register(ctx)
    _emit(receipt)
    return 0 if receipt.get("status") in ("planned", "completed") else 1


def cmd_status(a: argparse.Namespace) -> int:
    _emit(kit.status(_ctx(a, ())))
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    doc = kit.doctor(_ctx(a, ()))
    try:  # honest probe: mcp extra absent → not-applicable, not a failure
        import mcp  # noqa: F401
    except ImportError:
        doc["checks"] = [
            c if c["id"] != "mcp-handshake" else {
                **c, "status": "UNVERIFIED",
                "detail": "extra 'mcp' not installed — handshake not tested"}
            for c in doc["checks"]
        ]
        if not any(c["status"] == "FAIL" for c in doc["checks"]):
            doc["status"] = ("healthy" if doc["status"] != "broken"
                             else doc["status"])
    _emit(doc)
    return 1 if doc.get("status") in ("degraded", "broken") else 0


def cmd_repair(a: argparse.Namespace) -> int:
    ctx = _ctx(a, HOSTS)
    if a.dry_run:
        _emit(kit.status(ctx))
        return 0
    with kit.acquire_lock(ctx.state_dir):
        _emit(kit.repair(ctx))
    return 0


def cmd_uninstall(a: argparse.Namespace) -> int:
    ctx = _ctx(a, ())
    if a.dry_run:
        st = kit.status(ctx)
        _emit({"schema": kit.SCHEMA_RECEIPT, "forge_id": FORGE_ID,
               "operation": "uninstall", "scope": a.scope, "dry_run": True,
               "would_remove": st.get("drift", {}),
               "status": "planned",
               "verification": {"status": "UNVERIFIED"},
               "created_at": kit._utc_now()})
        return 0
    with kit.acquire_lock(ctx.state_dir):
        _emit(kit.uninstall(ctx, purge_state=a.purge))
    return 0


def cmd_update(a: argparse.Namespace) -> int:
    if a.to == "latest":
        _emit(_receipt("update", [{"id": "version", "status": "FAIL",
                                   "detail": "'latest' is never installable"}],
                       "failed"))
        return 1
    manifest = _installation_manifest()
    src = (Path(a.repo) if a.repo else
           Path(p) if (p := (manifest.get("source") or {}).get("path"))
           else None)
    if src is None or not src.exists():
        _emit(_receipt("update", [{"id": "source", "status": "FAIL",
                                   "detail": "no checkout registered — "
                                   "install via scripts/forge_bootstrap.py"}],
                       "BLOCKED"))
        return 1
    venv_dir = manifest.get("venv")
    if not venv_dir:
        _emit(_receipt("update", [{"id": "source", "status": "FAIL",
                                   "detail": "no venv registered; run "
                                   "scripts/forge_bootstrap.py"}], "failed"))
        return 1
    venv_py = Path(venv_dir) / ("Scripts/python.exe" if os.name == "nt"
                                else "bin/python")
    if not venv_py.exists():
        _emit(_receipt("update", [{"id": "venv", "status": "FAIL",
                                   "detail": f"venv {venv_dir} incomplete"}],
                       "failed"))
        return 1
    cmd = [str(venv_py), "-m", "pip", "install", "--upgrade", str(src)]
    if a.dry_run:
        _emit(_receipt("update", [{"id": "pip", "status": "UNVERIFIED",
                                   "detail": " ".join(cmd)}], "planned"))
        return 0
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                          check=False)
    checks = [{"id": "pip",
               "status": "PASS" if proc.returncode == 0 else "FAIL",
               "detail": (proc.stdout or proc.stderr)[-300:]}]
    doc = _receipt("update", checks,
                   "completed" if proc.returncode == 0 else "failed")
    _emit(doc)
    return 0 if proc.returncode == 0 else 1


def cmd_mcp_verify(a: argparse.Namespace) -> int:
    check = kit.mcp_verify(_spec())
    _emit({"schema": kit.SCHEMA_HEALTH, "forge_id": FORGE_ID,
           "status": ("healthy" if check["status"] == "PASS"
                      else "degraded" if check["status"] == "FAIL"
                      else "unverified"),
           "checks": [check], "checked_at": kit._utc_now(),
           "repair_hint": None})
    return 1 if check["status"] == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="forge_install.py",
                                 description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="op", required=True)

    def _base(p: argparse.ArgumentParser) -> None:
        p.add_argument("--scope", choices=SCOPES, default="project")
        p.add_argument("--root", default=None)
        p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("install", help="apply the portable install")
    _base(p)
    p.add_argument("--host", default="all")
    p.add_argument("--profile", choices=PROFILES, default="recommended")
    p.add_argument("--components", default=None,
                   help="optional components csv: skills,agents,mcp,tui,graph-studio")
    p.add_argument("--yes", "-y", action="store_true")
    p.set_defaults(fn=cmd_install)

    for name, fn in (("status", cmd_status), ("doctor", cmd_doctor),
                     ("repair", cmd_repair)):
        p = sub.add_parser(name)
        _base(p)
        p.set_defaults(fn=fn)

    p = sub.add_parser("uninstall")
    _base(p)
    p.add_argument("--purge", action="store_true")
    p.set_defaults(fn=cmd_uninstall)

    p = sub.add_parser("update")
    p.add_argument("--to", default=None)
    p.add_argument("--repo", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("mcp-verify")
    p.set_defaults(fn=cmd_mcp_verify)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except kit.InstallError as exc:
        _emit(exc.document(FORGE_ID))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
