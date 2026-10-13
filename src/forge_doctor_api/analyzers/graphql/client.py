"""GraphQL client query extraction (§184).

Static evidence only: ``gql``-tagged template literals (JS/TS) and
``gql("...")`` calls (Python). Queries that fail to parse or that are
interpolated/dynamic are recorded as UnknownFacts - never guessed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from forge_doctor_api.analyzers.graphql.model import (
    GraphQLClientQuery,
    GraphQLOperationKind,
    GraphQLProjectModel,
)
from forge_doctor_api.analyzers.graphql.shape import list_field_table, query_shape
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation, UnknownFact

# gql`...` / graphql`...` tagged templates; gql("""...""") python calls.
_TAGGED = re.compile(r"(?:gql|graphql)`([^`]*)`", re.DOTALL)
_PY_CALL = re.compile(r"gql\(\s*(?:'''|\"\"\"|')(.*?)(?:'''|\"\"\"|')\s*\)", re.DOTALL)
_INTERPOLATION = re.compile(r"\$\{|\+|\bformat\(|\b%\s")
_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".py", ".graphql", ".gql"}

_KIND_MAP = {
    "query": GraphQLOperationKind.QUERY,
    "mutation": GraphQLOperationKind.MUTATION,
    "subscription": GraphQLOperationKind.SUBSCRIPTION,
}


def extract_client_queries(
    context: ProjectContext, files: list[str], model: GraphQLProjectModel
) -> tuple[tuple[GraphQLClientQuery, ...], tuple[UnknownFact, ...]]:
    """Parse statically-visible client queries; dynamic ones → UnknownFacts."""
    from forge_doctor_api.analyzers.graphql.parser import _graphql

    gql = _graphql()
    queries: list[GraphQLClientQuery] = []
    unknowns: list[UnknownFact] = []
    table = list_field_table(model) if model.types else None

    for path in sorted(files):
        if Path(path).suffix.lower() not in _SOURCE_SUFFIXES:
            continue
        try:
            text = context.read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        for match in _extract_strings(path, text):
            raw, line = match
            if gql is None:
                unknowns.append(
                    UnknownFact(
                        subject=f"{path}:{line}",
                        missing="graphql-core parser",
                        resolution="install the 'graphql' extra",
                    )
                )
                continue
            try:
                doc = gql.parse(raw)
            except Exception:
                unknowns.append(
                    UnknownFact(
                        subject=f"{path}:{line}",
                        missing="a statically parseable query string",
                        resolution="the query is dynamic or malformed",
                    )
                )
                continue
            if _INTERPOLATION.search(raw):
                unknowns.append(
                    UnknownFact(
                        subject=f"{path}:{line}",
                        missing="interpolation-free query text",
                        resolution="the query embeds runtime values",
                    )
                )
                continue
            ops = [
                d
                for d in doc.definitions
                if d.__class__.__name__ == "OperationDefinitionNode"
            ]
            for op in ops:
                shape = query_shape(
                    doc, table, model=model, operation=(op.name.value if op.name else None)
                )
                touched = _touched_fields(op, doc, table)
                queries.append(
                    GraphQLClientQuery(
                        operation=op.name.value if op.name else None,
                        operation_kind=_KIND_MAP.get(
                            str(getattr(op.operation, "value", "query")),
                            GraphQLOperationKind.QUERY,
                        ),
                        shape=shape,
                        fields_touched=touched,
                        location=SourceLocation(path=path, line=line),
                    )
                )
    return tuple(queries), tuple(unknowns)


def _extract_strings(path: str, text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    if path.endswith((".ts", ".tsx", ".js", ".jsx")):
        for m in _TAGGED.finditer(text):
            out.append((m.group(1), text[: m.start()].count("\n") + 1))
    else:
        for m in _PY_CALL.finditer(text):
            out.append((m.group(1), text[: m.start()].count("\n") + 1))
        if path.endswith((".graphql", ".gql")):
            out.append((text, 1))
    return out


def _touched_fields(
    op: Any, doc: Any, table: dict[str, dict[str, Any]] | None
) -> tuple[str, ...]:
    """Resolve selections to ``Type.field`` pairs when the schema is known."""
    if table is None:
        return ()
    kind = str(getattr(op.operation, "value", "query"))
    root = {"query": "Query", "mutation": "Mutation", "subscription": "Subscription"}.get(
        kind
    )
    fragments = {
        d.name.value: d
        for d in doc.definitions
        if d.__class__.__name__ == "FragmentDefinitionNode"
    }
    touched: set[str] = set()

    def walk(sel_set: Any, parent: str | None, seen: frozenset[str]) -> None:
        if sel_set is None:
            return
        for sel in sel_set.selections:
            name = sel.__class__.__name__
            if name == "FieldNode":
                if parent:
                    touched.add(f"{parent}.{sel.name.value}")
                child = table.get(parent or "", {}).get(f"{sel.name.value}#type")
                walk(sel.selection_set, child, seen)
            elif name == "InlineFragmentNode":
                t = sel.type_condition.name.value if sel.type_condition else parent
                walk(sel.selection_set, t, seen)
            elif name == "FragmentSpreadNode":
                frag = fragments.get(sel.name.value)
                if frag is not None and sel.name.value not in seen:
                    t = (
                        frag.type_condition.name.value
                        if frag.type_condition
                        else parent
                    )
                    walk(frag.selection_set, t, seen | {sel.name.value})

    walk(op.selection_set, root, frozenset())
    return tuple(sorted(touched))
