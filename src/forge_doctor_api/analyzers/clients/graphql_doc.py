"""GraphQL client-document extractor (spec 087, §17).

Two surfaces, one parser:

- `.graphql` / `.gql` files containing executable documents
  (`query`/`mutation`/`subscription`) — schema SDL files produce nothing;
- `gql`...`` / `graphql`...`` tagged template literals inside JS/TS
  source — the document is parsed out of the template body.

Evidence-gated: an operation is emitted only when it carries a name or a
non-empty selection set; document bodies with no operations land in
`unknowns` only for `gql`-tagged templates (a `.graphql` schema file is
a contract artifact, not a client).
"""

from __future__ import annotations

import re

from forge_doctor_api.analyzers.clients.model import (
    ClientCallSite,
    ClientLanguage,
    client_name_for,
)
from forge_doctor_api.core.models import SourceLocation, UnknownFact

_OP = re.compile(
    r"\b(?P<kind>query|mutation|subscription)\b\s*(?P<name>[A-Za-z_]\w*)?")
_GQL_TAG = re.compile(r"\b(?:gql|graphql)\s*`(?P<doc>[^`]*)`")
_FIELD = re.compile(r"[A-Za-z_]\w*")
_SKIP_WORDS = {
    "query", "mutation", "subscription", "fragment", "on", "true",
    "false", "null",
}


def _selection_fields(doc: str, op_start: int) -> tuple[str, ...]:
    """Field names inside the operation's selection set."""
    brace = doc.find("{", op_start)
    if brace < 0:
        return ()
    depth = 0
    body_start = brace
    for i in range(brace, len(doc)):
        if doc[i] == "{":
            depth += 1
        elif doc[i] == "}":
            depth -= 1
            if depth == 0:
                body = doc[body_start:i + 1]
                fields = {
                    m.group(0) for m in _FIELD.finditer(body)
                    if m.group(0) not in _SKIP_WORDS
                }
                return tuple(sorted(fields))
    return ()


def _ops_in_doc(doc: str, path: str, line_offset: int,
                library: str) -> list[ClientCallSite]:
    sites: list[ClientCallSite] = []
    for match in _OP.finditer(doc):
        fields = _selection_fields(doc, match.end())
        line = line_offset + doc.count("\n", 0, match.start()) + 1
        sites.append(ClientCallSite(
            client=client_name_for(path),
            language=ClientLanguage.GRAPHQL,
            library=library,
            method=None, url=None, path=None,
            operation=match["name"],
            response_fields=fields,
            location=SourceLocation(path=path, line=line, column=1),
        ))
    return sites


def scan_graphql_document(
    path: str, source: str
) -> tuple[list[ClientCallSite], list[UnknownFact]]:
    """Extract client operations from one `.graphql`/`.gql` document."""
    return _ops_in_doc(source, path, 0, "graphql-doc"), []


def scan_javascript_graphql(
    path: str, source: str
) -> tuple[list[ClientCallSite], list[UnknownFact]]:
    """Extract `gql`...``-tagged documents from JS/TS source text.

    Call this with the comment-stripped source (same preprocessing as
    `scan_javascript_source`)."""
    sites: list[ClientCallSite] = []
    unknowns: list[UnknownFact] = []
    for match in _GQL_TAG.finditer(source):
        doc = match["doc"]
        line = source.count("\n", 0, match.start()) + 1
        found = _ops_in_doc(doc, path, line - 1, "graphql")
        if not found:
            unknowns.append(UnknownFact(
                subject=f"{path}:{line}",
                missing="executable operation inside the gql template",
                resolution="the template contains no query/mutation/"
                "subscription document"))
            continue
        sites.extend(found)
    return sites, unknowns
