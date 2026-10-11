"""The Forge Command Center — bare-``theforge`` interactive home.

Shows real state (specialists lifecycle, detected hosts, recent
delegations) and a menu whose every entry runs a real operation — no
decorative buttons. On a non-TTY the caller keeps the classic summary.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from forge_doctor_api.ui import i18n
from forge_doctor_api.ui.kit import NonInteractive, UIContext, _c, dashboard, select

_MENU = (
    "specialists",
    "run a task",
    "hosts",
    "graph studio",
    "install wizard",
    "install status",
    "health check",
    "recent tasks",
    "quit",
)


def _specialist_rows() -> list[tuple[str, str]]:
    from theforge import specialists

    rows = []
    for v in specialists.collect(workspace_root=Path.cwd().parent, probe_cli=False):
        state = v.lifecycle.installation_state
        detail = v.cli or (f"checkout:{Path(v.checkout).name}" if v.checkout else "-")
        rows.append((v.lifecycle.provider, f"{state}  {detail}"))
    return rows or [("(none)", "no catalog specialists")]


def _host_rows() -> list[tuple[str, str]]:
    from theforge import host_detect

    result = host_detect.detect_hosts(project_root=Path.cwd())
    return [
        (
            d.host,
            ("running" if d.running else "detected" if d.detected else "not detected")
            + f" ({d.confidence_basis})",
        )
        for d in result.detections
    ]


def _recent_rows(limit: int = 5) -> list[tuple[str, str]]:
    d = Path.cwd() / ".forge" / "delegations"
    if not d.is_dir():
        return [("(none)", "no delegations yet")]
    files = sorted(d.glob("task-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for f in files[:limit]:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            rows.append(
                (doc.get("task_id", f.stem), f"{doc.get('provider', '?')} {doc.get('stage', '?')}")
            )
        except (OSError, json.JSONDecodeError):
            continue
    return rows or [("(none)", "no delegations yet")]


def show_dashboard(ctx: UIContext) -> None:
    ws = Path.cwd().name
    dashboard(
        f"THE FORGE  workspace: {ws}",
        [
            ("Specialists", _specialist_rows()),
            ("Hosts", _host_rows()),
            ("Recent tasks", _recent_rows(3)),
        ],
        ctx=ctx,
    )


def _run_task(ctx: UIContext) -> None:
    from theforge import delegation, specialists
    from forge_doctor_api.ui.kit import prompt

    intent = prompt("What would you like to accomplish?", ctx=ctx)
    if not intent:
        return
    views = specialists.collect(workspace_root=Path.cwd().parent, probe_cli=False)
    requests = []
    for v in views:
        if v.manifest is None or not v.manifest.workflows:
            continue
        picked = specialists.select_workflow(v.manifest.workflows, intent)
        if isinstance(picked, str):
            from forge_doctor_api.ui.kit import select

            chosen = select(
                f"{v.lifecycle.provider} — which workflow?",
                [f"{w.id} — {w.description or w.mode}" for w in v.manifest.workflows],
                ctx=ctx,
            )
            if chosen is None:
                continue
            wf = v.manifest.workflows[chosen]
        else:
            wf = picked
        argv = specialists.resolve_command(wf.command, view=v, target=str(Path.cwd()))
        if argv is None:
            continue
        requests.append(
            delegation.new_request(
                intent=intent,
                provider=v.lifecycle.provider,
                execution_mode=wf.mode,
                command=argv,
            )
        )
    if not requests:
        print(_c(ctx, "33", "  no delegable specialist resolved an executable command"))
        return
    print(f"  {len(requests)} delegation(s) prepared:")
    for r in requests:
        print(f"    {r.provider}: {' '.join(r.command[:4])}…")
    from forge_doctor_api.ui.kit import confirm

    if not confirm("Execute?", default=True, ctx=ctx):
        return
    d = Path.cwd() / ".forge" / "delegations"
    d.mkdir(parents=True, exist_ok=True)
    for r in requests:
        result = delegation.execute(r, cwd=str(Path.cwd()))
        (d / f"{result.task_id}.json").write_text(
            json.dumps(dataclasses.asdict(result), indent=2), encoding="utf-8"
        )
        color = "32" if result.stage == "COMPLETED" else "31"
        print(f"  {result.provider}: {_c(ctx, color, result.stage)} exit={result.exit_code}")


def _act_specialists(ctx: UIContext) -> None:
    from forge_doctor_api.ui.kit import status_table

    rows = []
    for v in __import__("theforge.specialists", fromlist=["x"]).collect(
        workspace_root=Path.cwd().parent, probe_cli=False
    ):
        rows.append((v.lifecycle.provider, v.lifecycle.installation_state, v.cli or "-"))
    status_table(rows, ctx=ctx, headers=("specialist", "state", "cli"))


def _act_hosts(ctx: UIContext) -> None:
    from theforge import host_detect

    result = host_detect.detect_hosts(project_root=Path.cwd())
    for d in result.detections:
        mark = "*" if d.running else " "
        state = "DETECTED" if d.detected else "not detected"
        print(f"{mark} {d.host:<10} {state}  ({d.confidence_basis})")


def _act_health(ctx: UIContext) -> None:
    from theforge.install import service
    from forge_doctor_api.ui.kit import format_status_doc

    health = service.doctor(scope="project")
    print(format_status_doc(health, ctx=ctx))


def _act_install_status(ctx: UIContext) -> None:
    from theforge.install import service
    from forge_doctor_api.ui.kit import format_status_doc

    print(format_status_doc(service.status(scope="project"), ctx=ctx))


def _act_recent(ctx: UIContext) -> None:
    for name, detail in _recent_rows(10):
        print(f"  {name:<20} {detail}")


def _act_graph(ctx: UIContext) -> int:
    """Federated Graph Studio — real provider views, namespaced merge."""
    from theforge import graphview
    from theforge.graphstudio import graph_studio_enabled, open_studio

    if not graph_studio_enabled(Path.cwd()):
        print("  graph studio disabled at install (components.json: graph_studio=false)")
        return 0
    views, notes = graphview.federated_views(workspace_root=Path.cwd().parent)
    local = graphview.capability_view(root=Path.cwd())
    views.insert(0, local)
    for n in notes:
        print(f"  note: {n}")
    merged = graphview.federated_merge(views) if len(views) > 1 else local
    return open_studio([merged], open_browser=True)


def _act_install(ctx: UIContext) -> int:
    from theforge.install import service
    from forge_doctor_api.ui.wizard import run_wizard

    return run_wizard(
        forge_name="the-forge",
        install_fn=lambda **kw: service.install(root=None, **kw),
        doctor_fn=lambda **kw: service.doctor(**kw),
        ctx=ctx,
    )


def run_home(*, ctx: UIContext | None = None) -> int:
    """Command Center loop. Returns exit code; raises NonInteractive off-TTY."""
    ctx = ctx or UIContext.detect()
    if not ctx.interactive:
        raise NonInteractive("home requires a TTY")
    if ctx.ansi:  # full-screen path; ANSI-free terminals keep the inline kit
        from forge_doctor_api.ui.tui import run_tui

        return run_tui(ctx=ctx)
    actions = {
        "specialists": _act_specialists,
        "run a task": _run_task,
        "hosts": _act_hosts,
        "graph studio": _act_graph,
        "install wizard": _act_install,
        "install status": _act_install_status,
        "health check": _act_health,
        "recent tasks": _act_recent,
    }
    show_dashboard(ctx)
    while True:
        idx = select(
            i18n.t("choose", ctx.language),
            list(_MENU),
            ctx=ctx,
        )
        if idx is None or _MENU[idx] == "quit":
            return 0
        label = _MENU[idx]
        print()
        rc = actions[label](ctx)
        if isinstance(rc, int) and rc != 0:
            return rc
        print()
