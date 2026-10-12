from forge_doctor_api.ui import screen, tui
from forge_doctor_api.ui.app import ActionData, Entry, ForgeApp, TextData
from forge_doctor_api.ui.kit import UIContext
from forge_doctor_api.ui.screen import Buffer, Column, Theme, key_bar, table


def _ctx(width=60, height=16):
    return UIContext(
        interactive=False,
        color=False,
        unicode=False,
        width=width,
        height=height,
        ansi=False,
    )


def test_narrow_table_keeps_flexible_column_visible():
    buf = Buffer(_ctx(), 31, 10)
    table(
        buf,
        2,
        1,
        27,
        8,
        columns=[
            Column(key="name", title="name", width=28),
            Column(key="detail", title="detail"),
        ],
        rows=[{"name": "specialist", "detail": "ready"}],
        theme=Theme(),
    )
    rendered = "\n".join(buf.render())
    assert "NAME" in rendered and "DETAIL" in rendered and "ready" in rendered


def test_long_navigation_keeps_selected_item_rendered():
    entries = [Entry(label=f"item-{i}", provider=lambda: TextData(lines=["ok"])) for i in range(30)]
    app = ForgeApp(_ctx(), forge_id="forge-doctor-api", title="t", entries=entries)
    for _ in range(25):
        app.on_key("down")
    buf = Buffer(_ctx(), 60, 16)
    app.render(buf)
    assert "item-25" in "\n".join(buf.render())


def test_suspended_action_runs_without_capture():
    seen = []
    app = ForgeApp(
        _ctx(),
        forge_id="forge-doctor-api",
        title="t",
        entries=[
            Entry(
                label="go",
                provider=lambda: ActionData(
                    callable=lambda: seen.append("ran"),
                    title="run",
                    suspend=True,
                ),
            )
        ],
    )
    action = app.pane.data
    assert isinstance(action, ActionData)
    app._execute(action, capture=False)
    assert seen == ["ran"]
    assert "attached terminal" in "\n".join(app.pane.log)


def test_empty_menu_renders_empty_state():
    app = ForgeApp(_ctx(), forge_id="forge-doctor-api", title="t", entries=[])
    buf = Buffer(_ctx(), 60, 16)
    app.render(buf)
    assert "no menu entries" in "\n".join(buf.render())


def test_command_palette_finds_and_opens_entry():
    entries = [
        Entry(label="status", provider=lambda: TextData(lines=["ok"])),
        Entry(label="installation health", provider=lambda: TextData(lines=["healthy"])),
    ]
    app = ForgeApp(_ctx(), forge_id="forge-doctor-api", title="t", entries=entries)
    app.on_key("ctrl-k")
    for key in "health":
        app.on_key(key)
    app.on_key("enter")
    assert app.nav_idx == 1
    assert isinstance(app.pane.data, TextData)
    assert app.focus == "content"
    assert not app.palette_active


def test_shortcut_footer_stays_inside_viewport():
    buf = Buffer(_ctx(31, 10), 31, 10)
    key_bar(
        buf,
        [("ctrl-k", "commands"), ("enter", "open"), ("?", "help"), ("q", "quit")],
        theme=Theme(),
    )
    assert len(buf.render()[-1]) <= 31
    assert "ctrl-k" in buf.render()[-1]


def test_captured_command_timeout_returns_actionable_exit(monkeypatch, capsys):
    monkeypatch.setattr(tui.home, "_cli_argv", lambda _extra: ["forge-doctor-api"])

    def timeout(*_args, **_kwargs):
        raise tui.subprocess.TimeoutExpired(["forge-doctor-api"], 300)

    monkeypatch.setattr(tui.subprocess, "run", timeout)
    action = tui._action_for("slow status", ["status"])
    assert action.callable() == 124
    assert "timed out" in capsys.readouterr().out


def test_buffer_viewport_matrix_stays_bounded():
    for width, height in ((60, 16), (80, 24), (100, 30), (120, 40), (160, 50)):
        buf = Buffer(_ctx(width, height), width, height)
        buf.draw(0, 0, "left")
        buf.draw(0, width - 5, "right")
        assert len(buf.render()[0]) <= width


def test_posix_reader_exits_on_eof_and_normalizes_csi(monkeypatch):
    if screen.os.name == "nt":
        return
    import select as select_module

    class ClosedStdin:
        def fileno(self):
            return 0

    monkeypatch.setattr(screen.sys, "stdin", ClosedStdin())
    monkeypatch.setattr(select_module, "select", lambda *args: ([0], [], []))
    monkeypatch.setattr(screen.os, "read", lambda *_args: b"")
    assert screen.read_key(0) == "ctrl-d"
    chunks = iter((b"\x1b", b"[", b"A"))
    monkeypatch.setattr(screen.os, "read", lambda *_args: next(chunks))
    assert screen.read_key(0) == "up"
