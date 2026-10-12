"""Generic full-screen Forge app — nav pane + content pane, real providers.

Every entry renders *real* data: a provider callable returns one of:

- ``TableData(columns, rows, on_enter)`` — selectable table
- ``TextData(lines)`` — read-only detail/log
- ``ActionData(callable, title)`` — ``enter`` executes for real and the
  captured output streams into the content pane
- ``StateSpec`` — any of the mandatory state views

No fake buttons: a provider that fails renders the ``error`` state with
the real exception message; an empty provider renders ``empty``.
"""

from __future__ import annotations

import io
import sys
import traceback
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import TextIO

from forge_doctor_api.ui.kit import NonInteractive, UIContext, terminal_size
from forge_doctor_api.ui.screen import (
    MIN_HEIGHT,
    MIN_WIDTH,
    Buffer,
    Column,
    Screen,
    StateSpec,
    Theme,
    header,
    key_bar,
    panel,
    read_key,
    state_view,
    table,
    too_small,
)


@dataclass(kw_only=True)
class TableData:
    columns: list[Column]
    rows: list[dict[str, str]]
    on_enter: Callable[[dict[str, str]], None] | None = None


@dataclass(kw_only=True)
class TextData:
    lines: list[str]


@dataclass(kw_only=True)
class DocMeta:
    """Contextual doc metadata for an action (Forge Knowledge §21):
    description, prerequisites, example, risk, expected result and the
    canonical doc — a pointer, never an inlined manual."""

    description: str = ""
    prerequisites: str = ""
    example: str = ""
    risk: str = ""
    expected: str = ""
    doc_path: str = ""


@dataclass(kw_only=True)
class ActionData:
    callable: Callable[[], object]
    title: str
    # suspend=True → exit alt-screen + cooked stdin before calling
    # (wizards, subprocess prompts); Screen is re-entered after.
    suspend: bool = False
    doc: DocMeta | None = None


@dataclass(kw_only=True)
class Entry:
    label: str
    provider: Callable[[], TableData | TextData | ActionData | StateSpec]


@dataclass(kw_only=True)
class _Pane:
    data: TableData | TextData | ActionData | StateSpec | None = None
    selected: int = 0
    executing: bool = False
    log: list[str] = field(default_factory=list)
    scroll: int = 0


_HELP = [
    ("up/dn", "nav"),
    ("enter", "open/run"),
    ("r", "refresh"),
    ("/", "filter"),
    ("?", "help"),
    ("q", "back/quit"),
]


def _doc_lines(d: "ActionData") -> list[str]:
    """Render DocMeta as compact labelled lines (pointer, not manual)."""
    if d.doc is None:
        return []
    doc = d.doc
    out = [""]
    for label, val in (
        ("what", doc.description),
        ("needs", doc.prerequisites),
        ("example", doc.example),
        ("risk", doc.risk),
        ("expected", doc.expected),
        ("docs", doc.doc_path),
    ):
        if val:
            out.append(f"  {label:8s} {val}")
    return out


class ForgeApp:
    """Two-pane full-screen app: left nav, right content."""

    def __init__(
        self,
        ctx: UIContext,
        *,
        forge_id: str,
        title: str,
        entries: list[Entry],
        version: str = "",
        out: TextIO | None = None,
    ):
        self.ctx = ctx
        self.forge_id = forge_id
        self.title = title
        self.version = version
        self.entries = entries
        self.theme = Theme.for_forge(forge_id)
        self.nav_idx = 0
        self.focus = "nav"  # nav | content
        self.pane = _Pane()
        self.filter = ""
        self.filter_active = False
        self.show_help = False
        self._out = out
        self._load()

    # --------------------------------------------------------- data

    def _load(self) -> None:
        if not self.entries:
            self.pane = _Pane(data=StateSpec(kind="empty", title="no menu entries"))
            return
        entry = self.entries[self.nav_idx]
        try:
            data = entry.provider()
        except Exception as exc:  # real error state, never a lie
            data = StateSpec(
                kind="error",
                title="provider failed",
                detail=str(exc) or exc.__class__.__name__,
                hint="press r to retry",
            )
        self.pane = _Pane(data=data)

    def _visible_entries(self) -> list[tuple[int, Entry]]:
        f = self.filter.lower()
        return [(i, e) for i, e in enumerate(self.entries) if not f or f in e.label.lower()]

    # --------------------------------------------------------- render

    def render(self, buf: Buffer) -> None:
        ctx, th = self.ctx, self.theme
        header(buf, self.forge_id, self.title, theme=th, right=self.version)
        nav_w = max(22, min(34, buf.width // 4))
        ix, iy, iw, ih = panel(
            buf,
            0,
            2,
            nav_w,
            buf.height - 5,
            title=f"menu /{self.filter}" if self.filter_active or self.filter else "menu",
            focused=self.focus == "nav",
            theme=th,
        )
        vis = self._visible_entries()
        ids = [i for i, _ in vis]
        selected_pos = ids.index(self.nav_idx) if self.nav_idx in ids else 0
        start = min(max(0, selected_pos - ih + 1), max(0, len(vis) - ih))
        for row, (i, e) in enumerate(vis[start : start + ih]):
            marker = "> " if i == self.nav_idx else "  "
            style = th.focus if (i == self.nav_idx and self.focus == "nav" and ctx.color) else ""
            buf.draw(iy + row, ix - 1, marker + e.label, style=style)
        # content pane
        cx, cy, cw, ch = panel(
            buf,
            nav_w,
            2,
            buf.width - nav_w,
            buf.height - 5,
            title=self.entries[self.nav_idx].label if self.entries else "menu",
            focused=self.focus == "content",
            theme=th,
        )
        self._render_content(buf, cx, cy, cw, ch)
        if self.show_help:
            self._render_help(buf)
        key_bar(buf, _HELP, theme=th)

    def _render_content(self, buf: Buffer, x: int, y: int, w: int, h: int) -> None:
        d = self.pane.data
        if d is None:
            return
        if isinstance(d, StateSpec):
            sub = Buffer(buf.ctx, w, h)
            state_view(sub, d, theme=self.theme)
            for row, line in enumerate(sub.render()):
                buf.draw(y + row, x, line)
            return
        if isinstance(d, TableData):
            if not d.rows:
                sub = Buffer(buf.ctx, w, h)
                state_view(
                    sub,
                    StateSpec(kind="empty", title="no rows", detail="nothing to show"),
                    theme=self.theme,
                )
                for row, line in enumerate(sub.render()):
                    buf.draw(y + row, x, line)
                return
            table(
                buf,
                x + 1,
                y,
                w - 2,
                h,
                columns=d.columns,
                rows=d.rows,
                selected=self.pane.selected,
                theme=self.theme,
            )
            return
        lines = (
            d.lines
            if isinstance(d, TextData)
            else (
                [f"action: {d.title}"]
                + _doc_lines(d)
                + ["", "press enter to execute"]
                + self.pane.log
            )
        )
        for i, line in enumerate(lines[self.pane.scroll : self.pane.scroll + h]):
            buf.draw(y + i, x, line)

    def _render_help(self, buf: Buffer) -> None:
        w, h = min(56, buf.width - 4), min(14, buf.height - 4)
        x0, y0 = (buf.width - w) // 2, (buf.height - h) // 2
        ix, iy, iw, ih = panel(buf, x0, y0, w, h, title="keys", theme=self.theme)
        rows = [
            "up / k · down / j      move",
            "enter                  open / run / select",
            "tab                    switch pane",
            "r                      refresh real data",
            "/                      filter menu",
            "?                      this help",
            "esc / q                back · quit",
            "ctrl-c                 immediate quit",
        ]
        for i, line in enumerate(rows[:ih]):
            buf.draw(iy + i, ix, line, style="dim")

    # --------------------------------------------------------- keys

    def on_key(self, key: str) -> str | None:
        if key in ("ctrl-c", "ctrl-d"):
            return "quit"
        if self.filter_active:
            return self._filter_key(key)
        if self.show_help:
            self.show_help = False
            return None
        if key == "?":
            self.show_help = True
            return None
        if key == "/":
            self.filter_active = True
            self.focus = "nav"
            return None
        if key in ("tab", "backtab"):
            self.focus = "content" if self.focus == "nav" else "nav"
            return None
        if self.focus == "nav":
            return self._nav_key(key)
        return self._content_key(key)

    def _filter_key(self, key: str) -> str | None:
        if key in ("enter", "tab", "backtab"):
            self.filter_active = False
            return None
        if key == "esc":
            self.filter = ""
            self.filter_active = False
            self._sync_filter_selection()
            return None
        if key == "backspace":
            self.filter = self.filter[:-1]
            self._sync_filter_selection()
            return None
        char = key[5:] if key.startswith("char:") else key
        if len(char) == 1 and ord(char) >= 32:
            self.filter += char
            self._sync_filter_selection()
        return None

    def _sync_filter_selection(self) -> None:
        visible = self._visible_entries()
        if visible and self.nav_idx not in {i for i, _ in visible}:
            self.nav_idx = visible[0][0]
            self._load()

    def _nav_key(self, key: str) -> str | None:
        vis = self._visible_entries()
        if not vis:
            if key in ("q", "esc"):
                return "quit"
            return None
        if key in ("up", "k"):
            ids = [i for i, _ in vis]
            pos = ids.index(self.nav_idx) if self.nav_idx in ids else 0
            nxt = ids[(pos - 1) % len(ids)] if ids else 0
            if nxt != self.nav_idx:
                self.nav_idx = nxt
                self._load()
        elif key in ("down", "j"):
            ids = [i for i, _ in vis]
            pos = ids.index(self.nav_idx) if self.nav_idx in ids else 0
            nxt = ids[(pos + 1) % len(ids)] if ids else 0
            if nxt != self.nav_idx:
                self.nav_idx = nxt
                self._load()
        elif key == "enter":
            self.focus = "content"
        elif key in ("q", "esc"):
            return "quit"
        elif key == "r":
            self._load()
        return None

    def _content_key(self, key: str) -> str | None:
        d = self.pane.data
        if key in ("q", "esc"):
            self.focus = "nav"
            return None
        if key == "r":
            self._load()
            return None
        if isinstance(d, TableData) and d.rows:
            if key in ("up", "k"):
                self.pane.selected = max(0, self.pane.selected - 1)
            elif key in ("down", "j"):
                self.pane.selected = min(len(d.rows) - 1, self.pane.selected + 1)
            elif key == "pageup":
                self.pane.selected = max(0, self.pane.selected - 10)
            elif key == "pagedown":
                self.pane.selected = min(len(d.rows) - 1, self.pane.selected + 10)
            elif key == "home":
                self.pane.selected = 0
            elif key == "end":
                self.pane.selected = len(d.rows) - 1
            elif key == "enter" and d.on_enter:
                try:
                    d.on_enter(d.rows[self.pane.selected])
                except Exception as exc:
                    self.pane = _Pane(
                        data=StateSpec(
                            kind="error",
                            title="row action failed",
                            detail=str(exc) or exc.__class__.__name__,
                            hint="press r to retry",
                        )
                    )
                else:
                    self._load()
        elif isinstance(d, ActionData) and key == "enter":
            return "exec"  # loop decides suspend vs in-place
        elif isinstance(d, (TextData, ActionData)):
            line_count = len(d.lines) if isinstance(d, TextData) else len(self.pane.log) + 8
            if key in ("up", "k"):
                self.pane.scroll = max(0, self.pane.scroll - 1)
            elif key in ("down", "j"):
                self.pane.scroll = min(max(0, line_count - 1), self.pane.scroll + 1)
            elif key == "pageup":
                self.pane.scroll = max(0, self.pane.scroll - 10)
            elif key == "pagedown":
                self.pane.scroll = min(max(0, line_count - 1), self.pane.scroll + 10)
            elif key == "home":
                self.pane.scroll = 0
            elif key == "end":
                self.pane.scroll = max(0, line_count - 1)
        return None

    def _execute(self, d: ActionData, *, capture: bool = True) -> None:
        """Run real callable; capture inline or leave suspended output attached."""
        self.pane.log = [f"$ {d.title}", ""]
        sink = io.StringIO()
        try:
            if capture:
                with redirect_stdout(sink), redirect_stderr(sink):
                    result = d.callable()
            else:
                result = d.callable()
        except Exception:
            self.pane.log += ["", "FAILED:", traceback.format_exc(limit=3)]
            return
        out = sink.getvalue() if capture else ""
        if capture:
            self.pane.log += out.rstrip().splitlines() or ["(no output)"]
        else:
            self.pane.log.append("(output streamed in attached terminal)")
        if result is not None:
            self.pane.log += ["", f"exit: {result}"]
        self.pane.log += ["", "— done · r refresh · esc back"]

    # --------------------------------------------------------- run

    def run(self) -> int:
        ctx = self.ctx
        if not (ctx.interactive and ctx.ansi):
            raise NonInteractive("TUI requires an ANSI TTY")
        with Screen(ctx, out=self._out or sys.stdout) as scr:
            size = (0, 0)
            while True:
                now = (ctx.width, ctx.height)
                now = terminal_size(
                    stream=self._out or sys.stdout,
                    fallback=(ctx.width, ctx.height),
                )
                if now != size:
                    size = now
                    self.ctx = UIContext(**{**ctx.__dict__, "width": size[0], "height": size[1]})
                    ctx = self.ctx
                buf = Buffer(ctx, size[0], size[1])
                if size[0] < MIN_WIDTH or size[1] < MIN_HEIGHT:
                    too_small(buf, theme=self.theme)
                else:
                    self.render(buf)
                scr.flush(buf)
                key = read_key()
                if key is None:
                    continue
                action = self.on_key(key)
                if action == "quit":
                    return 0
                if action == "exec":
                    d = self.pane.data
                    if isinstance(d, ActionData):
                        if d.suspend:
                            scr.__exit__(None, None, None)
                            try:
                                self._execute(d, capture=False)
                            finally:
                                scr.__enter__()
                        else:
                            self._execute(d)
