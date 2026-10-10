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

from forge_doctor_api.ui.kit import NonInteractive, UIContext
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
class ActionData:
    callable: Callable[[], object]
    title: str
    # suspend=True → exit alt-screen + cooked stdin before calling
    # (wizards, subprocess prompts); Screen is re-entered after.
    suspend: bool = False


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


_HELP = [("up/dn", "nav"), ("enter", "open/run"), ("r", "refresh"),
         ("/", "filter"), ("?", "help"), ("q", "back/quit")]


class ForgeApp:
    """Two-pane full-screen app: left nav, right content."""

    def __init__(self, ctx: UIContext, *, forge_id: str, title: str,
                 entries: list[Entry], version: str = "",
                 out: TextIO | None = None):
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
        self.show_help = False
        self._out = out
        self._load()

    # --------------------------------------------------------- data

    def _load(self) -> None:
        entry = self.entries[self.nav_idx]
        try:
            data = entry.provider()
        except Exception as exc:  # real error state, never a lie
            data = StateSpec(kind="error", title="provider failed",
                             detail=str(exc) or exc.__class__.__name__,
                             hint="press r to retry")
        self.pane = _Pane(data=data)

    def _visible_entries(self) -> list[tuple[int, Entry]]:
        f = self.filter.lower()
        return [(i, e) for i, e in enumerate(self.entries)
                if not f or f in e.label.lower()]

    # --------------------------------------------------------- render

    def render(self, buf: Buffer) -> None:
        ctx, th = self.ctx, self.theme
        header(buf, self.forge_id, self.title, theme=th,
               right=self.version)
        nav_w = max(22, min(34, buf.width // 4))
        ix, iy, iw, ih = panel(buf, 0, 2, nav_w, buf.height - 5,
                               title="menu", focused=self.focus == "nav",
                               theme=th)
        vis = self._visible_entries()
        for row, (i, e) in enumerate(vis[:ih]):
            if row >= ih:
                break
            marker = "> " if i == self.nav_idx else "  "
            style = th.focus if (i == self.nav_idx and self.focus == "nav"
                                 and ctx.color) else ""
            buf.draw(iy + row, ix - 1, marker + e.label, style=style)
        # content pane
        cx, cy, cw, ch = panel(buf, nav_w, 2, buf.width - nav_w,
                               buf.height - 5,
                               title=self.entries[self.nav_idx].label,
                               focused=self.focus == "content", theme=th)
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
                state_view(sub, StateSpec(kind="empty", title="no rows",
                                          detail="nothing to show"),
                           theme=self.theme)
                for row, line in enumerate(sub.render()):
                    buf.draw(y + row, x, line)
                return
            table(buf, x + 1, y, w - 2, h, columns=d.columns, rows=d.rows,
                  selected=self.pane.selected, theme=self.theme)
            return
        lines = d.lines if isinstance(d, TextData) else (
            [f"action: {d.title}", "", "press enter to execute"] + self.pane.log)
        for i, line in enumerate(lines[:h]):
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
        if key == "ctrl-c":
            return "quit"
        if self.show_help:
            self.show_help = False
            return None
        if key == "?":
            self.show_help = True
            return None
        if key == "/":
            self.filter = ""  # placeholder toggles filter line; keep simple
            self.focus = "nav"
            return None
        if key == "tab":
            self.focus = "content" if self.focus == "nav" else "nav"
            return None
        if self.focus == "nav":
            return self._nav_key(key)
        return self._content_key(key)

    def _nav_key(self, key: str) -> str | None:
        vis = self._visible_entries()
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
            elif key == "enter" and d.on_enter:
                d.on_enter(d.rows[self.pane.selected])
                self._load()
        elif isinstance(d, ActionData) and key == "enter":
            return "exec"  # loop decides suspend vs in-place
        return None

    def _execute(self, d: ActionData) -> None:
        """Run the real callable; capture its stdout into the pane."""
        self.pane.log = [f"$ {d.title}", ""]
        sink = io.StringIO()
        try:
            with redirect_stdout(sink), redirect_stderr(sink):
                result = d.callable()
        except Exception:
            self.pane.log += ["", "FAILED:", traceback.format_exc(limit=3)]
            return
        out = sink.getvalue()
        self.pane.log += out.rstrip().splitlines() or ["(no output)"]
        if result is not None:
            self.pane.log += ["", f"exit: {result}"]
        self.pane.log += ["", "— done · r refresh · esc back"]

    # --------------------------------------------------------- run

    def run(self) -> int:
        ctx = self.ctx
        if not (ctx.interactive and ctx.ansi):
            raise NonInteractive("TUI requires an ANSI TTY")
        import os
        with Screen(ctx, out=self._out or sys.stdout) as scr:
            size = (0, 0)
            while True:
                now = (ctx.width, ctx.height)
                try:
                    sz = os.get_terminal_size()
                    now = (sz.columns, sz.lines)
                except OSError:
                    pass
                if now != size:
                    size = now
                    self.ctx = UIContext(**{**ctx.__dict__,
                                            "width": size[0], "height": size[1]})
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
                                self._execute(d)
                            finally:
                                scr.__enter__()
                        else:
                            self._execute(d)
