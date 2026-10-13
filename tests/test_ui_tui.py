"""TUI/menu contract tests — vendored ui.* surface."""

import pytest


def test_menu_well_formed():
    """Every _MENU item is a (label, argv|None) pair — no bare strings."""
    from forge_doctor_api.ui import home
    for item in home._MENU:
        assert isinstance(item, tuple) and len(item) == 2, item
        label, argv = item
        assert isinstance(label, str) and label
        assert argv is None or argv in ("__wizard__", "__diff__") or isinstance(argv, list)


def _registered(root):
    names = set()
    subs = {}
    for info in root.registered_commands:
        names.add(info.name or info.callback.__name__.replace("_", "-"))
    for group in root.registered_groups:
        names.add(group.name)
        subs[group.name] = group.typer_instance
    return names, subs


def test_menu_argv_resolves_against_real_commands():
    """Menu argv[0] is a registered command/group (argv[1] a subcommand of
    it), or a `__script__` sentinel pointing at a real checkout script —
    a menu entry the real surface can't run is a broken promise."""
    from forge_doctor_api.cli import app
    from forge_doctor_api.ui import home
    top, groups = _registered(app)
    for label, argv in home._MENU:
        if argv is None or argv in ("__wizard__", "__diff__"):
            continue
        assert isinstance(argv, list) and argv, label
        if argv[0] == "__script__":
            script = home._script_root() / "scripts" / argv[1]
            assert script.is_file(), f"{label!r}: {argv[1]} not found"
            continue
        assert argv[0] in top, f"{label!r}: {argv[0]!r} is not a real command"
        if argv[0] in groups and len(argv) > 1 and not argv[1].startswith("-"):
            sub_names, _ = _registered(groups[argv[0]])
            assert argv[1] in sub_names, (
                f"{label!r}: {argv[1]!r} is not a real subcommand of {argv[0]!r}"
            )


def test_tui_entries_real():
    from forge_doctor_api.ui import tui
    entries = tui.entries()
    assert len(entries) >= 3
    assert any("wizard" in e.label for e in entries)


def test_tui_renders_non_tty_ctx():
    from forge_doctor_api.ui import tui
    from forge_doctor_api.ui.app import ForgeApp
    from forge_doctor_api.ui.kit import UIContext
    from forge_doctor_api.ui.screen import Buffer
    ctx = UIContext(interactive=False, color=False, unicode=False,
                    width=80, height=24, ansi=False)
    app = ForgeApp(ctx, forge_id="x", title="cc", entries=tui.entries())
    buf = Buffer(ctx, 80, 24)
    app.render(buf)
    assert "menu" in chr(10).join(buf.render())


def test_home_requires_tty():
    from forge_doctor_api.ui import home
    from forge_doctor_api.ui.kit import NonInteractive, UIContext
    ctx = UIContext(interactive=False, color=False, unicode=False, width=80)
    with pytest.raises(NonInteractive):
        home.run_home(ctx=ctx)
