# Accessibility

The UI kit is stdlib-only and capability-detected:

- **Keyboard-first**: every action is reachable via arrows/Enter/Space/
  Esc — no mouse required anywhere.
- **No color dependency**: `NO_COLOR` and `TERM=dumb` strip all ANSI
  styling; state is always carried by text (`OK`/`FAIL`/status words),
  never by color alone.
- **Narrow terminals**: content truncates with a visible ellipsis
  instead of wrapping or hiding; minimum useful width is 80 columns.
- **Limited charset**: on non-UTF-8 codepages the kit falls back to
  ASCII glyphs (`>`, `x`, `->`).
- **Reduced motion**: no animations — menus redraw in place on keypress
  only.
- **Screen readers / automation**: every interactive flow has a linear
  headless equivalent (flags + JSON output); see `automation.md`.

## Language

`FORGE_LANG=pt|en` selects the UI language (pt-BR and en built in);
locale detection is the fallback. Technical terms stay untranslated.
