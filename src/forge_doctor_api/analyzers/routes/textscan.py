"""Comment/string stripping for non-Python adapters (adversarial).

The problem a regex-only scanner cannot solve honestly: structural
matches (``@GetMapping``, ``app.get(``, ``@Controller``) may live inside
comments or string literals, and matching them produces fake routes.
The fix is a single character-level pass producing ``StrippedSource``:

- ``safe`` -- the source with comment interiors and string interiors
  blanked to spaces (newlines preserved, so positions and line numbers
  in ``safe`` map 1:1 to the original text). Structural patterns run
  against ``safe``; nothing inside a comment or string can match.
- ``literals`` -- every string literal's (start, end, value) so an
  argument position inside a matched call can be *resolved* back to
  its literal content: ``@GetMapping("/pets")`` shows up in ``safe`` as
  ``@GetMapping("     ")``; ``literal_at(pos)`` recovers ``/pets``.

Dynamic content (template interpolation, concatenation, non-literal
args) yields no literal -- the adapter records an UnknownFact rather
than guessing.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass


@dataclass(frozen=True)
class StrippedSource:
    """Position-preserving stripped view of one source file."""

    text: str
    safe: str
    literals: tuple[tuple[int, int, str], ...]

    def literal_at(self, pos: int) -> str | None:
        """Value of the string literal containing `pos` (its opening quote)."""
        starts = [start for start, _, _ in self.literals]
        i = bisect.bisect_right(starts, pos) - 1
        if i < 0:
            return None
        start, end, value = self.literals[i]
        return value if start <= pos < end else None


def strip_source(text: str) -> StrippedSource:
    """Strip comments and string literals from Java/JS-family source.

    Line comments ``//`` run to newline; block comments ``/* */`` are
    nest-free; single, double, and backtick strings honor backslash
    escapes; Java text blocks ``\"\"\"`` are blanked like any string.
    ``${}`` inside a template is therefore never structurally visible,
    which is exactly the honest behaviour: interpolated paths are not
    static evidence.
    """
    safe = list(text)
    literals: list[tuple[int, int, str]] = []
    i, n = 0, len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if safe[k] != "\n":
                safe[k] = " "

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif text.startswith('"""', i) or ch in "\"'`":
            if text.startswith('"""', i):
                quote, j = '"""', i + 3
                while j < n and not text.startswith('"""', j):
                    j += 1
                j = min(n, j + 3)
            else:
                quote, j = ch, i + 1
                while j < n and text[j] != quote:
                    j += 2 if text[j] == "\\" else 1
                j = min(n, j + 1)
            literals.append(
                (i, j,
                 text[i + len(quote): max(i + len(quote), j - len(quote))]))
            blank(i + len(quote), max(i + len(quote), j - len(quote)))
            i = j
        else:
            i += 1
    return StrippedSource(
        text=text, safe="".join(safe), literals=tuple(literals))


def line_of(text: str, pos: int) -> int:
    """1-based line number of `pos` in `text`."""
    return text.count("\n", 0, pos) + 1
