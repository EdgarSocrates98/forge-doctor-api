"""Java client extractor: Feign call sites (spec 087, §17).

Regex-based, dependency-free — same posture as the JS extractor.
Evidence-gated: a site is emitted only inside a `@FeignClient`-annotated
type or when the file imports `feign.RequestLine`; method-level
annotations without a literal path land in `unknowns`, never guessed.

- `@RequestLine("GET /orders/{id}")` -> method+path
- `@GetMapping("/orders")` / `@PostMapping` / … -> method+path
- `@RequestMapping(method = RequestMethod.POST, value = "/o")` -> both
- class-level `@RequestMapping("/api")` prefixes method paths when both
  are literals.
"""

from __future__ import annotations

import re

from forge_doctor_api.analyzers.clients.model import (
    ClientCallSite,
    ClientLanguage,
    client_name_for,
)
from forge_doctor_api.core.models import SourceLocation, UnknownFact

_FEIGN_TYPE = re.compile(r"@FeignClient\b")
_REQUESTLINE_IMPORT = re.compile(r"\bimport\s+feign\.RequestLine\b")
_REQUESTLINE = re.compile(r'@RequestLine\s*\(\s*"(?P<spec>[^"]+)"')
_MAPPING = re.compile(
    r"@(?P<ann>Get|Post|Put|Delete|Patch|Head|Options)Mapping\b"
    r"(?:\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?\"(?P<path>[^\"]*)\")?",
)
_REQUEST_MAPPING = re.compile(
    r'@RequestMapping\s*\((?P<args>[^)]*)\)', re.S)
_RM_METHOD = re.compile(r"RequestMethod\.(?P<m>[A-Z]+)")
_RM_VALUE = re.compile(r'(?:value|path)\s*=\s*"(?P<p>[^"]*)"')
_RM_POSITIONAL = re.compile(r'^\s*"(?P<p>[^"]*)"')


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _join(prefix: str | None, path: str | None) -> str | None:
    if path is None:
        return None
    if not prefix:
        return path if path.startswith("/") else "/" + path
    return prefix.rstrip("/") + (path if path.startswith("/") else "/" + path)


def scan_java_source(
    path: str, source: str
) -> tuple[list[ClientCallSite], list[UnknownFact]]:
    """Extract Feign call sites from one Java source file."""
    sites: list[ClientCallSite] = []
    unknowns: list[UnknownFact] = []
    if not (_FEIGN_TYPE.search(source) or _REQUESTLINE_IMPORT.search(source)):
        return sites, unknowns

    # class-level @RequestMapping prefix (first occurrence before `interface`
    # / `class` keyword is the client type's base path)
    prefix: str | None = None
    head = source.split("interface ", 1)[0]
    m = _REQUEST_MAPPING.search(head)
    if m:
        v = _RM_VALUE.search(m["args"]) or _RM_POSITIONAL.search(m["args"])
        prefix = v["p"] if v else None

    for match in _REQUESTLINE.finditer(source):
        spec = match["spec"].strip()
        verb, _, p = spec.partition(" ")
        if not p.startswith("/"):
            p = "/" + p if p else None
        line = _line(source, match.start())
        if p is None:
            unknowns.append(UnknownFact(
                subject=f"{path}:{line}",
                missing="literal path in @RequestLine",
                resolution="the annotation uses a computed path"))
            continue
        sites.append(ClientCallSite(
            client=client_name_for(path),
            language=ClientLanguage.JAVA,
            library="feign",
            method=verb.upper() if verb.upper() in {
                "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS",
            } else None,
            url=_join(prefix, p),
            path=_join(prefix, p),
            location=SourceLocation(path=path, line=line, column=1),
        ))

    for match in _MAPPING.finditer(source):
        line = _line(source, match.start())
        raw = match["path"]
        if raw is not None and not raw.startswith("/"):
            raw = "/" + raw if raw else None
        joined = _join(prefix, raw)
        if joined is None:
            unknowns.append(UnknownFact(
                subject=f"{path}:{line}",
                missing="literal path in mapping annotation",
                resolution="the annotation uses a computed path"))
            continue
        sites.append(ClientCallSite(
            client=client_name_for(path),
            language=ClientLanguage.JAVA,
            library="feign",
            method=match["ann"].upper(),
            url=joined,
            path=joined,
            location=SourceLocation(path=path, line=line, column=1),
        ))

    for match in _REQUEST_MAPPING.finditer(source):
        args = match["args"]
        method_m = _RM_METHOD.search(args)
        value_m = _RM_VALUE.search(args) or _RM_POSITIONAL.search(args)
        line = _line(source, match.start())
        if method_m is None:
            continue  # class-level prefix or unannotated — not a call site
        joined = _join(prefix, value_m["p"] if value_m else None)
        if joined is None:
            unknowns.append(UnknownFact(
                subject=f"{path}:{line}",
                missing="literal path in @RequestMapping",
                resolution="the annotation uses a computed path"))
            continue
        sites.append(ClientCallSite(
            client=client_name_for(path),
            language=ClientLanguage.JAVA,
            library="feign",
            method=method_m["m"],
            url=joined,
            path=joined,
            location=SourceLocation(path=path, line=line, column=1),
        ))
    return sites, unknowns
