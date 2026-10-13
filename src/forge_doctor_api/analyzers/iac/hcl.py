"""Bounded HCL2 surface scanner (spec 055).

NOT an HCL parser: it strips comments/heredocs/strings, extracts
top-level `resource "TYPE" "NAME" { ... }` block headers and depth-1
`key = literal` attributes. Anything nested or dynamic (`count`,
`for_each`, expressions, function calls, references) becomes
`None` + an UnknownFact — never a guess. No external dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from forge_doctor_api.analyzers.routes.textscan import (
    line_of,
    strip_source,
)
from forge_doctor_api.core.models import SourceLocation, UnknownFact

_BLOCK_HEAD = re.compile(
    r'\bresource\s+"[^"\n]*"\s+"[^"\n]*"\s*\{')
_QUOTED = re.compile(r'"[^"\n]*"')
_ATTR = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S.*?)\s*$')
_HEREDOC = re.compile(r'<<-?\s*"?([A-Za-z_][A-Za-z0-9_]*)"?')
_DYNAMIC_KEYS = ("count", "for_each")
_SCALAR = re.compile(r'-?\d+(\.\d+)?|true|false|null')


@dataclass(frozen=True, kw_only=True)
class TfAttr:
    name: str
    value: str | None          # resolved literal or None (dynamic)
    location: SourceLocation
    dynamic: bool = False


@dataclass(frozen=True, kw_only=True)
class TfBlock:
    type_name: str
    name: str
    attrs: tuple[TfAttr, ...]
    location: SourceLocation
    existence_known: bool      # False when count/for_each unknown


def _blank_heredocs(text: str) -> str:
    """Blank `<<EOF ... EOF` bodies, preserving positions/newlines."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _HEREDOC.search(lines[i])
        if m:
            tag = m.group(1)
            i += 1
            while i < len(lines):
                if lines[i].strip() == tag:
                    lines[i] = " " * len(lines[i])
                    break
                lines[i] = " " * len(lines[i])
                i += 1
        i += 1
    return "\n".join(lines)


def _blank_hash_comments(safe: str) -> str:
    """Blank `#`-to-EOL on the already string-blanked view."""
    chars = list(safe)
    i = 0
    while i < len(chars):
        if chars[i] == "#":
            j = safe.find("\n", i)
            j = len(safe) if j < 0 else j
            for k in range(i, j):
                chars[k] = " "
            i = j
        else:
            i += 1
    return "".join(chars)


def parse_hcl(path: str, text: str) -> tuple[tuple[TfBlock, ...],
                                             tuple[UnknownFact, ...]]:
    """Extract resource blocks + literal attrs; dynamics -> unknowns."""
    text = _blank_heredocs(text)
    stripped = strip_source(text)
    safe = _blank_hash_comments(stripped.safe)

    blocks: list[TfBlock] = []
    unknowns: list[UnknownFact] = []
    for m in _BLOCK_HEAD.finditer(safe):
        quotes = list(_QUOTED.finditer(m.group(0)))
        if len(quotes) != 2:
            continue
        type_name = stripped.literal_at(m.start() + quotes[0].start())
        name = stripped.literal_at(m.start() + quotes[1].start())
        if type_name is None or name is None:
            continue
        loc = SourceLocation(path=path, line=line_of(safe, m.start()))
        # find matching close brace at depth 0
        depth, i = 1, m.end()
        while i < len(safe) and depth:
            if safe[i] == "{":
                depth += 1
            elif safe[i] == "}":
                depth -= 1
            i += 1
        body = safe[m.end():i - 1]
        base = m.end()

        attrs: list[TfAttr] = []
        existence_known = True
        seg_start, seg_depth = 0, 0
        j = 0
        while j < len(body):
            c = body[j]
            if c in "{[":
                seg_depth += 1
            elif c in "}]":
                seg_depth = max(0, seg_depth - 1)
            elif c == "\n" and seg_depth == 0:
                seg = body[seg_start:j]
                am = _ATTR.match(seg)
                if am:
                    aname = am.group(1)
                    aloc = SourceLocation(
                        path=path,
                        line=line_of(safe, base + seg_start))
                    # re-read raw value from the ORIGINAL text (literals
                    # intact) so quoted values resolve directly
                    raw = text[base + seg_start:base + j]
                    vm = _ATTR.match(raw)
                    rval = vm.group(2).strip() if vm else ""
                    if aname in _DYNAMIC_KEYS:
                        existence_known = False
                        unknowns.append(UnknownFact(
                            subject=f"{type_name}.{name}",
                            missing=f"resource existence ({aname} "
                                    "not literal)",
                            resolution="only a literal count > 0 marks "
                                       "existence; expressions never do"))
                    else:
                        value = _attr_literal(rval)
                        if value is None and rval:
                            unknowns.append(UnknownFact(
                                subject=f"{type_name}.{name}.{aname}",
                                missing="literal attribute value",
                                resolution="expressions/references are "
                                           "not evaluated"))
                        attrs.append(TfAttr(
                            name=aname, value=value, location=aloc,
                            dynamic=value is None and bool(rval)))
                seg_start = j + 1
            j += 1
        blocks.append(TfBlock(
            type_name=type_name, name=name, attrs=tuple(attrs),
            location=loc, existence_known=existence_known))
    return tuple(blocks), tuple(unknowns)


def _attr_literal(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        inner = raw[1:-1]
        if '"' in inner:
            return None                      # interpolation escaped edge
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    if _SCALAR.fullmatch(raw):
        return raw
    if raw.startswith("[") and raw.endswith("]"):
        parts = [p.strip() for p in raw[1:-1].split(",") if p.strip()]
        out: list[str] = []
        for p in parts:
            if p.startswith('"') and p.endswith('"'):
                out.append(p[1:-1])
            elif _SCALAR.fullmatch(p):
                out.append(p)
            else:
                return None
        return "[" + ",".join(out) + "]"
    return None
