# Accessibility

The UI kit is stdlib-only and capability-detected:

- **Keyboard-first**: every action is reachable via arrows/Enter/Space/
  Esc — no mouse required anywhere.
- **No color dependency**: `NO_COLOR` and `TERM=dumb` strip all ANSI
  styling; state is always carried by text (`OK`/`FAIL`/status words),
  never by color alone.
- **Narrow terminals**: full-screen layout requires 60×16; tables rebalance
  columns, menus keep selection visible, and values truncate explicitly.
- **Limited charset**: on non-UTF-8 codepages the kit falls back to
  ASCII glyphs (`>`, `x`, `->`).
- **Reduced motion**: no animations — menus redraw in place on keypress
  only.
- **Screen readers / automation**: every interactive flow has a linear
  headless equivalent (flags + JSON output); see `automation.md`.

## Terminal compatibility

Rui probes active terminal dimensions on each render cycle. It supports
80×24, 100×30, 120×40, and 160×50 layouts, plus smaller terminals through
the explicit `terminal too small` state. `NO_COLOR`, `TERM=dumb`, non-UTF-8
codepages, PowerShell, Windows Terminal, SSH, pipes, and closed input follow
capability-aware fallbacks. Real external PTY/ConPTY validation remains
unverified when no observable host session is available.

## Language

`FORGE_LANG=pt|en` selects the UI language (pt-BR and en built in);
locale detection is the fallback. Technical terms stay untranslated.
