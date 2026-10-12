from forge_doctor_api.ui.app import ActionData, Entry, ForgeApp, TextData
from forge_doctor_api.ui.kit import UIContext
from forge_doctor_api.ui.screen import Buffer, Column, Theme, table


def _ctx(width=60, height=16):
    return UIContext(interactive=False, color=False, unicode=False, width=width, height=height, ansi=False)


def test_narrow_table_keeps_flexible_column_visible():
    buf = Buffer(_ctx(), 31, 10)
    table(buf, 2, 1, 27, 8,
          columns=[Column(key="name", title="name", width=28), Column(key="detail", title="detail")],
          rows=[{"name": "specialist", "detail": "ready"}], theme=Theme())
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
    app = ForgeApp(_ctx(), forge_id="forge-doctor-api", title="t", entries=[
        Entry(label="go", provider=lambda: ActionData(callable=lambda: seen.append("ran"), title="run", suspend=True))
    ])
    action = app.pane.data
    assert isinstance(action, ActionData)
    app._execute(action, capture=False)
    assert seen == ["ran"]
    assert "attached terminal" in "\n".join(app.pane.log)
