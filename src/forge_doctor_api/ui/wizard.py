"""Guided installation wizard (Experience Program §1.2).

Drives the *real* install service — every choice maps to an actual
``install()`` call; the review step is the real dry-run plan, and the
apply step is the governed ``--yes`` path. Nothing here writes files
itself.

Flow: env check → scope → profile → hosts → review (dry-run plan) →
confirm → apply → doctor → finish. Any step can be cancelled (Esc/q)
without side effects; nothing is written before the explicit confirm.
"""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any

from forge_doctor_api.ui import i18n
from forge_doctor_api.ui.kit import (
    NonInteractive,
    UIContext,
    _c,
    confirm,
    dashboard,
    multi_select,
    select,
)

_ALL_HOSTS = ("claude", "devin", "codex", "copilot")
_PROFILES = ("recommended", "minimal", "full")  # service contract names
_PROFILE_LABELS = {
    "recommended": "Balanced (Recommended)",
    "minimal": "Economy",
    "full": "Full",
}
_SCOPE_LABELS = {
    "project": "Current repository",
    "workspace": "Entire workspace",
    "user": "My user account",
}


def env_check_rows() -> list[tuple[str, str]]:
    """Real environment evidence: python, git, host binaries."""
    v = sys.version_info
    rows = [("Python", f"{v.major}.{v.minor}.{v.micro}")]
    rows.append(("Git", "OK" if shutil.which("git") else "missing"))
    for h in _ALL_HOSTS:
        rows.append((h.capitalize(), "Available" if shutil.which(h) else "not detected"))
    return rows


def _banner(ctx: UIContext, forge_name: str) -> None:
    print()
    print(_c(ctx, "1", f" {forge_name.upper()}"))
    print(_c(ctx, "2", " " + ("─" if ctx.unicode else "-") * max(10, len(forge_name) + 4)))
    print(f"  {i18n.t('env_detected', ctx.language)}:")


def run_wizard(
    *,
    forge_name: str,
    install_fn: Any,
    doctor_fn: Any | None = None,
    hosts_available: tuple[str, ...] = _ALL_HOSTS,
    ctx: UIContext | None = None,
    out_json: bool = False,
) -> int:
    """Interactive install wizard. Returns exit code.

    ``install_fn(**kwargs)`` is the forge's real install service
    (``host``/``scope``/``profile``/``yes``/``dry_run`` kwargs).
    ``doctor_fn`` optionally verifies post-install.
    """
    ctx = ctx or UIContext.detect()
    if not ctx.interactive:
        raise NonInteractive("install wizard requires a TTY")

    _banner(ctx, forge_name)
    env_rows = env_check_rows()
    for label, val in env_rows:
        print(f"    {label:<14} {_c(ctx, '32' if val in ('OK', 'Available') else '2', val)}")
    print()

    # --- scope ---------------------------------------------------------------
    scopes = ["project", "workspace", "user"]
    idx = select(
        i18n.t("install_scope_q", ctx.language),
        [_SCOPE_LABELS[s] for s in scopes],
        ctx=ctx,
    )
    if idx is None:
        return 130
    scope = scopes[idx]

    # --- profile -------------------------------------------------------------
    idx = select(
        i18n.t("install_profile_q", ctx.language),
        [_PROFILE_LABELS[p] for p in _PROFILES],
        ctx=ctx,
    )
    if idx is None:
        return 130
    profile = _PROFILES[idx]

    # --- optional components ---------------------------------------------------
    # The profile decides the default; the operator can narrow or extend it.
    # "graph-studio"/"tui" are runtime flags persisted to components.json —
    # skills/agents/mcp map to real asset kinds.
    _COMP_LABELS = {
        "skills": "Skills",
        "agents": "Agents",
        "mcp": "MCP",
        "tui": "TUI",
        "graph-studio": "Graph Studio",
    }
    _COMP_ORDER = ("skills", "agents", "mcp", "tui", "graph-studio")
    _profile_defaults = {
        "minimal": {"mcp", "tui"},
        "recommended": {"skills", "mcp", "tui", "graph-studio"},
        "full": {"skills", "agents", "mcp", "tui", "graph-studio"},
    }
    comp_checked = _profile_defaults.get(profile, set())
    comp_chosen = multi_select(
        i18n.t("install_components_q", ctx.language),
        [_COMP_LABELS[c] for c in _COMP_ORDER],
        checked={i for i, c in enumerate(_COMP_ORDER) if c in comp_checked},
        ctx=ctx,
    )
    if comp_chosen is None:
        return 130
    components = tuple(
        sorted(_COMP_ORDER[i] for i in comp_chosen)
    )

    # --- hosts ---------------------------------------------------------------
    detected = {
        i
        for i, h in enumerate(hosts_available)
        if any(h in r[0].lower() and r[1] == "Available" for r in env_rows)
    }
    chosen = multi_select(
        i18n.t("install_hosts_q", ctx.language),
        list(hosts_available),
        checked=detected,
        ctx=ctx,
    )
    if chosen is None:
        return 130
    if not chosen:
        host_arg: str | None = None
    elif len(chosen) == len(hosts_available):
        host_arg = "all"
    else:
        host_arg = ",".join(hosts_available[i] for i in sorted(chosen))

    # --- review (real dry-run plan) ------------------------------------------
    # Contrato explicito: install_fn aceita `components` — wrappers **kw
    # encaminham sem inspecao de assinatura (GAP-002).
    kwargs: dict = {"scope": scope, "profile": profile, "components": components}
    try:
        # `none` e opt-out explicito — zero hosts escolhidos nunca vira
        # "all" (GAP-003); csv de subconjunto e contrato valido (GAP-003b).
        plan = install_fn(host=host_arg or "none", dry_run=True, **kwargs)
    except Exception as exc:
        print(_c(ctx, "31", f"plan failed: {exc}"))
        return 1

    planned = plan.get("planned") or plan.get("planned_files") or plan.get("writes") or []
    dashboard(
        f"{forge_name} — {i18n.t('review', ctx.language)}",
        [
            (
                "Plan",
                [
                    ("scope", scope),
                    ("profile", profile),
                    ("components", ", ".join(components) or "none"),
                    ("hosts", host_arg or "none"),
                    ("managed writes", str(len(planned) if isinstance(planned, list) else planned)),
                ],
            )
        ],
        ctx=ctx,
    )
    if isinstance(planned, list):
        for entry in planned[:10]:
            path = entry.get("path") if isinstance(entry, dict) else str(entry)
            print(f"    {_c(ctx, '2', path)}")
        if len(planned) > 10:
            print(f"    … {len(planned) - 10} more")

    if not confirm(i18n.t("confirm_q", ctx.language), default=True, ctx=ctx):
        return 130

    # --- apply (real governed install) ---------------------------------------
    receipt = install_fn(host=host_arg or "none", yes=True, dry_run=False, **kwargs)
    status = receipt.get("status", "unknown")
    if out_json:
        print(json.dumps(receipt, indent=2, ensure_ascii=False))
    color = "32" if status == "completed" else "31"
    print(f"\n  {i18n.t('status', ctx.language)}: {_c(ctx, color, status)}")

    # --- verify --------------------------------------------------------------
    if doctor_fn is not None and status == "completed":
        health = doctor_fn(scope=scope)
        hstatus = (health.get("status") or health.get("health") or {}).get("status", "unknown")
        color = "32" if hstatus in ("healthy", "PASS") else "33"
        print(f"  {i18n.t('health', ctx.language)}: {_c(ctx, color, str(hstatus))}")

    return 0 if status == "completed" else 1
