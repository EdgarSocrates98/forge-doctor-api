"""Full-screen TUI engine — stdlib only, zero dependencies.

Architecture (see ``docs/experience-3/design-system.md``):

- ``Theme`` — per-Forge accent + invariant state colors.
- ``Buffer`` — 2-D cell grid of styled text; ``render()`` is a pure
  function returning ANSI/plain lines. Business state never touches
  stdout: views draw into a Buffer and the loop flushes.
- ``Screen`` — context manager owning the terminal lifecycle:
  enter → alt screen + cursor hide + raw mode; exit → always restore
  (try/finally), even on SIGINT — the terminal is never left broken.
- ``run_loop`` — event loop: poll input ≤50 ms, redraw on state
  change or resize only. Non-TTY never enters alt screen; callers
  degrade to one-shot output or ``NonInteractive``.

State vocabulary is mandatory: every screen renders ``empty``,
``loading``, ``ready``, ``error``, ``disconnected`` or ``too_small``
from real state via ``state_view`` — never a broken layout.
"""

from __future__ import annotations

import os
import re
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TextIO

from forge_doctor_api.ui.kit import (
    NonInteractive,
    UIContext,
    _c,
    _ellipsize,
    _pad_visible,
    cell_width,
    terminal_size,
)

MIN_WIDTH = 60
MIN_HEIGHT = 16

# ---------------------------------------------------------------- theme

# Deterministic accent per forge_id — stable across processes, and the
# core never names a real provider (TestNoSpecialistNamesInCore).
_ACCENT_CYCLE = ("33", "34", "35", "36", "32", "37")


@dataclass(frozen=True, kw_only=True)
class Theme:
    """One accent per Forge; state colors invariant (design-system v1)."""

    accent: str = "36"
    ok: str = "32"
    warn: str = "33"
    err: str = "31"
    info: str = "36"
    dim: str = "2"
    focus: str = "7"  # reverse video

    @staticmethod
    def for_forge(forge_id: str) -> Theme:
        idx = sum(forge_id.encode("utf-8")) % len(_ACCENT_CYCLE)
        return Theme(accent=_ACCENT_CYCLE[idx])


_STATE_ICON_UNI = {
    "empty": "○",
    "loading": "…",
    "ready": "●",
    "ok": "✓",
    "error": "✗",
    "warn": "▲",
    "disconnected": "⚡",
    "too_small": "!",
}
_STATE_ICON_ASCII = {
    "empty": "o",
    "loading": "...",
    "ready": "*",
    "ok": "+",
    "error": "x",
    "warn": "!",
    "disconnected": "x",
    "too_small": "!",
}
_STATE_COLOR = {
    "empty": "dim",
    "loading": "info",
    "ready": "ok",
    "ok": "ok",
    "error": "err",
    "warn": "warn",
    "disconnected": "warn",
    "too_small": "warn",
}

_BOX_UNI = {"h": "─", "v": "│", "tl": "┌", "tr": "┐", "bl": "└", "br": "┘"}
_BOX_ASCII = {"h": "-", "v": "|", "tl": "+", "tr": "+", "bl": "+", "br": "+"}


def box(ctx: UIContext) -> dict[str, str]:
    return _BOX_UNI if ctx.unicode else _BOX_ASCII


def state_icon(ctx: UIContext, state: str) -> str:
    glyphs = _STATE_ICON_UNI if ctx.unicode else _STATE_ICON_ASCII
    return glyphs.get(state, glyphs["ready"])


# ---------------------------------------------------------------- buffer


@dataclass(kw_only=True)
class _Span:
    x: int
    text: str
    style: str = ""  # ANSI SGR code, "" = plain


_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


def _clip(text: str, width: int) -> str:
    """Hard cell-width clip — canvas chrome never gets an ellipsis marker."""
    if width <= 0:
        return ""
    out, used, pos = [], 0, 0
    for match in _SGR_RE.finditer(text):
        chunk = text[pos : match.start()]
        for ch in chunk:
            cw = cell_width(ch)
            if used + cw > width:
                return "".join(out) + "\x1b[0m" if out else ""
            out.append(ch)
            used += cw
        out.append(match.group(0))
        pos = match.end()
    for ch in text[pos:]:
        cw = cell_width(ch)
        if used + cw > width:
            break
        out.append(ch)
        used += cw
    return "".join(out)


class Buffer:
    """Fixed-size cell grid. ``draw()`` writes styled spans; ``render()``
    returns a list of finished lines (ANSI when ctx.color)."""

    def __init__(self, ctx: UIContext, width: int, height: int):
        self.ctx = ctx
        self.width = max(1, width)
        self.height = max(1, height)
        self._rows: list[list[_Span]] = [[] for _ in range(self.height)]

    def draw(self, y: int, x: int, text: str, *, style: str = "") -> None:
        if not (0 <= y < self.height) or x >= self.width:
            return
        x = max(0, x)
        clipped = _clip(text, self.width - x)
        if not clipped:
            return
        self._rows[y].append(_Span(x=x, text=clipped, style=style))

    def hline(self, y: int, x: int = 0, w: int | None = None, *, style: str = "") -> None:
        b = box(self.ctx)
        self.draw(y, x, b["h"] * (w if w is not None else self.width - x), style=style)

    def render(self) -> list[str]:
        """Flatten rows into printable lines (pure — no I/O)."""
        out: list[str] = []
        for spans in self._rows:
            if not spans:
                out.append("")
                continue
            cells = [" "] * self.width
            styles = [""] * self.width

            def paint(chunk: str, cursor: int, style: str) -> int:
                for ch in chunk:
                    cw = cell_width(ch)
                    if cw == 0:
                        if cursor and cells[cursor - 1] != "":
                            cells[cursor - 1] += ch
                        continue
                    if cursor >= self.width or cursor + cw > self.width:
                        break
                    cells[cursor] = ch
                    styles[cursor] = style
                    for offset in range(1, cw):
                        cells[cursor + offset] = ""
                        styles[cursor + offset] = style
                    cursor += cw
                return cursor

            for span in spans:
                cursor = max(0, span.x)
                active = span.style
                pos = 0
                for match in _SGR_RE.finditer(span.text):
                    cursor = paint(span.text[pos : match.start()], cursor, active)
                    code = match.group(1)
                    active = "" if code == "0" else code
                    pos = match.end()
                paint(span.text[pos:], cursor, active)

            rendered: list[str] = []
            current_style = ""
            segment: list[str] = []

            def flush() -> None:
                if not segment:
                    return
                text = "".join(segment)
                rendered.append(_c(self.ctx, current_style, text) if current_style else text)
                segment.clear()

            for ch, style in zip(cells, styles, strict=True):
                if ch == "":
                    continue
                if style != current_style:
                    flush()
                    current_style = style
                segment.append(ch)
            flush()
            out.append("".join(rendered))
        return out


# ---------------------------------------------------------------- layout


def panel(
    buf: Buffer,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    title: str = "",
    focused: bool = False,
    theme: Theme,
) -> tuple[int, int, int, int]:
    """Draw a bordered panel; returns inner (x, y, w, h) for content."""
    ctx = buf.ctx
    b = box(ctx)
    border_style = theme.accent if focused else theme.dim
    tl, tr, bl, br, hh, vv = b["tl"], b["tr"], b["bl"], b["br"], b["h"], b["v"]
    if w < 3 or h < 3:
        return x, y, w, h
    cap = f" {title} " if title else ""
    top = (
        tl + hh * (w - 2 - cell_width(cap)) + cap
        if False
        else (
            tl + cap + hh * max(0, w - 2 - cell_width(cap)) + tr
            if cell_width(cap) <= w - 2
            else tl + hh * (w - 2) + tr
        )
    )
    buf.draw(y, x, top, style=border_style)
    for row in range(1, h - 1):
        buf.draw(y + row, x, vv, style=border_style)
        buf.draw(y + row, x + w - 1, vv, style=border_style)
    buf.draw(y + h - 1, x, bl + hh * (w - 2) + br, style=border_style)
    return x + 2, y + 1, w - 4, h - 2


def key_bar(buf: Buffer, bindings: Iterable[tuple[str, str]], *, theme: Theme) -> None:
    """Footer line: ``key action · key action``."""
    y = buf.height - 1
    buf.hline(y - 1, style="2")
    parts = " · ".join(f"{_c(buf.ctx, '1' if buf.ctx.color else '', k)} {v}" for k, v in bindings)
    buf.draw(y, 1, re.sub(r"\x1b\[[0-9;]*m", "", parts) if not buf.ctx.color else parts)


def header(buf: Buffer, forge: str, screen: str, *, theme: Theme, right: str = "") -> None:
    """2-row header: brand line + accent rule."""
    ctx = buf.ctx
    brand = f" {forge.upper()} "
    sep = "·" if ctx.unicode else "-"
    title = f"{sep} {screen}" if screen else ""
    left = _c(ctx, theme.accent, brand) + _c(ctx, "dim", title) if ctx.color else brand + title
    buf.draw(0, 0, left)
    if right:
        buf.draw(0, max(0, buf.width - cell_width(right) - 1), right, style="dim")
    buf.hline(1, style=theme.accent)


# ---------------------------------------------------------------- states


@dataclass(kw_only=True)
class StateSpec:
    """A screen's real state — views render this, never hardcode."""

    kind: str = "ready"  # empty|loading|ready|error|disconnected|too_small|warn
    title: str = ""
    detail: str = ""
    hint: str = ""  # recovery hint ("press r to retry")


def state_view(buf: Buffer, state: StateSpec, *, theme: Theme) -> None:
    """Centered state panel for non-content screens (mandatory coverage)."""
    ctx = buf.ctx
    color = getattr(theme, _STATE_COLOR.get(state.kind, "dim"), "2")
    icon = state_icon(ctx, state.kind)
    cy = buf.height // 2
    line = f"{icon} {state.title or state.kind}"
    buf.draw(cy - 1, max(1, (buf.width - cell_width(line)) // 2), line, style=color)
    if state.detail:
        buf.draw(cy, max(1, (buf.width - cell_width(state.detail)) // 2), state.detail, style="dim")
    if state.hint:
        buf.draw(cy + 1, max(1, (buf.width - cell_width(state.hint)) // 2), state.hint)


def too_small(buf: Buffer, *, theme: Theme) -> None:
    state_view(
        buf,
        StateSpec(
            kind="too_small",
            title=f"terminal too small ({buf.width}x{buf.height})",
            detail=f"need at least {MIN_WIDTH}x{MIN_HEIGHT}",
            hint="resize to continue",
        ),
        theme=theme,
    )


# ---------------------------------------------------------------- table


@dataclass(kw_only=True)
class Column:
    key: str
    title: str
    width: int | None = None  # None = flexible


def _column_widths(width: int, columns: list[Column]) -> list[int]:
    """Fit fixed and flexible columns inside viewport, preserving every column."""
    if not columns:
        return []
    gaps = 2 * (len(columns) - 1)
    budget = max(len(columns), width - gaps)
    fixed = [i for i, column in enumerate(columns) if column.width is not None]
    flexible = [i for i, column in enumerate(columns) if column.width is None]
    widths = [1] * len(columns)
    flex_min = 8 if budget >= (len(flexible) * 8 + len(fixed)) else 1
    fixed_budget = max(0, budget - len(flexible) * flex_min)
    desired = [max(1, int(columns[i].width or 1)) for i in fixed]
    desired_total = sum(desired)
    if fixed:
        if desired_total <= fixed_budget:
            for i, value in zip(fixed, desired, strict=True):
                widths[i] = value
        else:
            remaining = fixed_budget
            for pos, (i, value) in enumerate(zip(fixed, desired, strict=True)):
                slots_left = len(fixed) - pos
                share = min(value, max(1, remaining - (slots_left - 1)))
                widths[i] = share
                remaining -= share
    remaining = max(0, budget - sum(widths[i] for i in fixed))
    for pos, i in enumerate(flexible):
        slots_left = len(flexible) - pos
        share = max(1, remaining // slots_left) if remaining else 1
        widths[i] = share
        remaining = max(0, remaining - share)
    return widths


def table(
    buf: Buffer,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    columns: list[Column],
    rows: list[dict[str, str]],
    selected: int = 0,
    theme: Theme,
) -> None:
    """Selectable table: fixed columns, flexible last column, scrolls."""
    ctx = buf.ctx
    widths = _column_widths(w, columns)
    # header
    cx = x
    for c, cw in zip(columns, widths, strict=True):
        buf.draw(y, cx, _pad_visible(c.title.upper()[:cw], cw), style="2")
        cx += cw + 2
    body_h = h - 2
    start = max(0, min(selected - body_h + 1, len(rows) - body_h))
    for i, row in enumerate(rows[start : start + body_h]):
        idx = start + i
        cx = x
        marker = ">" if idx == selected else " "
        buf.draw(y + 2 + i, x - 2, marker, style=theme.accent)
        for c, cw in zip(columns, widths, strict=True):
            text = _pad_visible(_ellipsize(ctx, row.get(c.key, ""), cw), cw)
            if idx == selected and ctx.color:
                buf.draw(y + 2 + i, cx, text, style=theme.focus)
            else:
                buf.draw(y + 2 + i, cx, text)
            cx += cw + 2


# ---------------------------------------------------------------- screen


class Screen:
    """Terminal lifecycle: alt-screen + raw + cursor-hide; always restores."""

    def __init__(self, ctx: UIContext, *, out: TextIO = sys.stdout):
        self.ctx = ctx
        self.out = out
        self._raw = None
        self._entered = False

    def __enter__(self) -> Screen:
        if not self.ctx.interactive or not self.ctx.ansi:
            raise NonInteractive("full-screen TUI requires an ANSI TTY")
        out = self.out
        out.write("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
        out.flush()
        self._raw = _RawMode().__enter__() if os.name != "nt" else None
        self._entered = True
        return self

    def __exit__(self, *exc) -> bool:
        if self._raw is not None:
            self._raw.__exit__(*exc)
        if self._entered:
            self.out.write("\x1b[?25h\x1b[?1049l")
            self.out.flush()
            self._entered = False
        return False

    def flush(self, buf: Buffer) -> None:
        """Full-buffer redraw (home + lines). Cheap enough ≤200 rows."""
        self.out.write("\x1b[H" + "\x1b[K\n".join(buf.render()) + "\x1b[K")
        self.out.flush()


class _RawMode:
    """POSIX raw mode; on Windows msvcrt keys are already raw."""

    def __enter__(self) -> _RawMode:
        if os.name != "nt" and sys.stdin.isatty():
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc) -> bool:
        if getattr(self, "_saved", None) is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        return False


_ESC = {
    "\x1b[A": "up",
    "\x1b[B": "down",
    "\x1b[C": "right",
    "\x1b[D": "left",
    "\x1b[H": "home",
    "\x1b[F": "end",
    "\x1b[5~": "pageup",
    "\x1b[6~": "pagedown",
    "\x1b[Z": "backtab",
}
_KEYS = {
    "\r": "enter",
    "\n": "enter",
    " ": "space",
    "\t": "tab",
    "\x1b": "esc",
    "\x7f": "backspace",
    "\x03": "ctrl-c",
}


def read_key(timeout: float = 0.05) -> str | None:
    """Non-blocking key read; returns a normalized name or None."""
    if os.name == "nt":
        import msvcrt

        if not msvcrt.kbhit():
            time.sleep(timeout)
            return None
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # special key prefix
            return {
                "H": "up",
                "P": "down",
                "M": "right",
                "K": "left",
                "G": "home",
                "O": "end",
                "I": "pageup",
                "Q": "pagedown",
            }.get(msvcrt.getwch(), "other")
        return _KEYS.get(ch, ch)
    # POSIX — select-based poll
    import select

    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if not r:
        return None
    try:
        ch = os.read(sys.stdin.fileno(), 1).decode(errors="replace")
    except OSError:
        return "ctrl-d"
    if not ch:
        return "ctrl-d"
    if ch != "\x1b":
        return _KEYS.get(ch) or ch
    seq = ch
    deadline = time.monotonic() + min(0.06, max(timeout, 0.0) + 0.01)
    while len(seq) < 8:
        remain = max(0.0, deadline - time.monotonic())
        if not remain:
            break
        ready, _, _ = select.select([sys.stdin], [], [], remain)
        if not ready:
            break
        try:
            part = os.read(sys.stdin.fileno(), 1).decode(errors="replace")
        except OSError:
            break
        if not part:
            break
        seq += part
        if seq in _ESC:
            return _ESC[seq]
        if part.isalpha() or part == "~":
            break
    return _ESC.get(seq, "esc")


# ---------------------------------------------------------------- loop


@dataclass(kw_only=True)
class LoopResult:
    key: str | None = None
    action: str = "quit"  # quit | select | back | custom
    index: int = 0


def run_loop(
    ctx: UIContext,
    render: Callable[[Buffer], None],
    on_key: Callable[[str], str | None] | None = None,
    *,
    forge: str = "the-forge",
    screen_title: str = "",
    theme: Theme | None = None,
    out: TextIO = sys.stdout,
) -> LoopResult:
    """Minimal event loop: render → poll key → dispatch → repeat.

    ``render(buf)`` draws the whole frame (pure). ``on_key(name)``
    returns an action string (``quit`` ends the loop) or None to
    keep running. Resize is detected each tick; too-small renders the
    dedicated state instead of a broken layout.
    """
    theme = theme or Theme.for_forge(forge)
    result = LoopResult()
    if not (ctx.interactive and ctx.ansi):
        raise NonInteractive("full-screen TUI requires an ANSI TTY")
    with Screen(ctx, out=out) as scr:
        size = (0, 0)
        while True:
            now = (ctx.width, ctx.height)
            # refresh size every tick (SIGWINCH arrives between polls)
            now = terminal_size(fallback=(ctx.width, ctx.height))
            if now != size:
                size = now
                ctx = UIContext(**{**ctx.__dict__, "width": size[0], "height": size[1]})
            buf = Buffer(ctx, size[0], size[1])
            if size[0] < MIN_WIDTH or size[1] < MIN_HEIGHT:
                too_small(buf, theme=theme)
            else:
                render(buf)
            scr.flush(buf)
            key = read_key()
            if key is None:
                continue
            if key in ("ctrl-c", "ctrl-d") or (key in ("q", "esc") and on_key is None):
                return result
            action = on_key(key) if on_key else None
            if action == "quit":
                return result
            if action:
                result.action = action
                result.key = key
                return result
