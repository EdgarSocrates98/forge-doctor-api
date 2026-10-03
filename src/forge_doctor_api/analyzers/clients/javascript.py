"""JS/TS client extractor: `fetch`/`axios` call sites (§17).

Conservative static scan — no JS parser dependency:

- comments (`//` and `/* */`) are stripped before matching, so decorator
  text in comments cannot produce call sites;
- call arguments are extracted by balanced-paren scanning that skips string
  contents, so `(` inside a URL string cannot break extraction;
- a call site is emitted only when the URL is a literal string (including
  template literals without `${}`); anything else lands in `unknowns`.
- response fields: `x = <resp>.json()` bindings feed `x.field`/`x["f"]`
  access collection, plus `r => r.field` arrow bodies on `.json()` chains.
"""

from __future__ import annotations

import re

from forge_doctor_api.analyzers.clients.model import (
    ClientCallSite,
    ClientLanguage,
    client_name_for,
)
from forge_doctor_api.core.models import SourceLocation, UnknownFact

_CALL = re.compile(
    r"\bfetch\s*\("  # fetch(
    r"|\baxios\s*\.\s*(?P<ax_method>get|post|put|delete|patch|head|options)\s*\("
    r"|\baxios(?:\s*\.\s*request)?\s*\("
)
_STRING = re.compile(r"^([\"'`])(?P<body>(?:\\.|(?!\1).)*)\1", re.S)
_KV = re.compile(r"\b(?P<key>url|method)\s*:\s*(?P<q>[\"'`])(?P<val>[^\"'`]*)(?P=q)")
_JSON_BIND = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:await\s+)?\w+\s*\.\s*json\s*\(")
_ARROW_FIELD = re.compile(r"(?<!\w)(\w+)\s*=>\s*\1\s*\.\s*(\w+)")
_FIELD_DOT = re.compile(r"(?<![.\w])(?P<var>\w+)\s*\.\s*(?P<field>\w+)")
_FIELD_SUB = re.compile(r"(?<![.\w])(?P<var>\w+)\s*\[\s*[\"'](?P<field>\w+)[\"']\s*\]")


def _strip_comments(source: str) -> str:
    """Blank out comment content, preserving offsets and newlines.

    String-aware: `//` inside a string literal (e.g. `"https://x"`) is never
    treated as a comment start.
    """
    out = list(source)
    i = 0
    quote: str | None = None
    while i < len(source):
        ch = source[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "/" and source[i:i + 2] == "//":
            j = source.find("\n", i)
            end = len(source) if j < 0 else j
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        elif ch == "/" and source[i:i + 2] == "/*":
            j = source.find("*/", i + 2)
            end = len(source) if j < 0 else j + 2
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def _args_span(text: str, open_paren: int) -> tuple[int, int]:
    """Return (start, end) of the argument list; -1 end when unbalanced."""
    depth = 0
    i = open_paren
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return open_paren + 1, i
        i += 1
    return open_paren + 1, -1


def _literal_arg(args: str) -> str | bool | None:
    """First positional arg as a literal string; False = dynamic, None = absent."""
    match = _STRING.match(args.lstrip())
    if not match:
        return False if args.strip() else None
    body = match["body"]
    if match.group(1) == "`" and "${" in body:
        return False  # interpolated template literal
    return body


def _method_in_args(args: str) -> str | None:
    for match in _KV.finditer(args):
        if match["key"] == "method":
            return match["val"].upper()
    return None


def _url_in_object(args: str) -> str | None:
    for match in _KV.finditer(args):
        if match["key"] == "url":
            return match["val"]
    return None


def _url_path(url: str) -> str | None:
    rest = url
    if "://" in rest:
        rest = rest.split("://", 1)[1].partition("/")[2]
        rest = "/" + rest if rest else "/"
    if not rest.startswith("/"):
        rest = "/" + rest
    return rest.split("?", 1)[0] or None


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    return line, offset - text.rfind("\n", 0, offset)


def _response_fields(text: str) -> frozenset[str]:
    fields: set[str] = {m.group(2) for m in _ARROW_FIELD.finditer(text)}
    bound = {m.group(1) for m in _JSON_BIND.finditer(text)}
    for match in _FIELD_DOT.finditer(text):
        if match["var"] in bound:
            fields.add(match["field"])
    for match in _FIELD_SUB.finditer(text):
        if match["var"] in bound:
            fields.add(match["field"])
    return frozenset(fields)


def scan_javascript_source(
    path: str, source: str
) -> tuple[list[ClientCallSite], list[UnknownFact]]:
    text = _strip_comments(source)
    sites: list[ClientCallSite] = []
    unknowns: list[UnknownFact] = []
    for match in _CALL.finditer(text):
        open_paren = text.index("(", match.start())
        start, end = _args_span(text, open_paren)
        if end < 0:
            continue
        args = text[start:end]
        token = match.group(0)
        location = SourceLocation(path=path, line=_line_col(text, match.start())[0], column=1)

        if token.startswith("fetch"):
            url = _literal_arg(args)
            method = _method_in_args(args) or "GET"
            library = "fetch"
        elif match["ax_method"]:
            library = "axios"
            method = match["ax_method"].upper()
            url = _literal_arg(args)
            if url is False and args.lstrip().startswith("{"):
                url = _url_in_object(args)
                url = url if url is not None else False
                method = _method_in_args(args) or method
        else:  # axios(...) or axios.request(...)
            library = "axios"
            url = _url_in_object(args)
            method = (_method_in_args(args) or "GET")
            if url is None:
                url = _literal_arg(args)

        if not isinstance(url, str):
            unknowns.append(
                UnknownFact(
                    subject=f"{path}:{location.line}",
                    missing="literal URL for the client call",
                    resolution="the call uses a computed or interpolated URL",
                )
            )
            continue
        sites.append(
            ClientCallSite(
                client=client_name_for(path),
                language=ClientLanguage.JAVASCRIPT,
                library=library,
                method=method,
                url=url,
                path=_url_path(url),
                response_fields=tuple(sorted(_response_fields(text))),
                location=location,
            )
        )
    return sites, unknowns
