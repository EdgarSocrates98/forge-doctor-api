"""GraphQLQueryShape - §24 transparent complexity metrics.

All metrics are counts, not scores:

- ``depth``: deepest selection-set nesting (fragments expanded once,
  cycles guarded)
- ``field_count``: total field selections
- ``list_expansions``: selections whose schema type is a list
- ``resolver_count``: distinct parent types traversed (approximation of
  resolver invocations)
- ``estimated_complexity`` = ``field_count + list_expansions * depth``

When a schema is unavailable for a metric (e.g. list detection), the
value falls back to a documented constant and the caller records an
UnknownFact - never a guessed score.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from forge_doctor_api.analyzers.graphql.model import (
    GraphQLProjectModel,
    GraphQLQueryShape,
)

if TYPE_CHECKING:
    pass


def query_shape(
    document: Any,
    schema_types: dict[str, Any] | None = None,
    *,
    model: GraphQLProjectModel | None = None,
    operation: Any | None = None,
) -> GraphQLQueryShape:
    """Compute §24 metrics for a parsed graphql-core operation/fragment doc.

    `document` is a graphql-core `DocumentNode`. `schema_types`, when
    provided, maps type name -> field name -> is_list flag (built from a
    `GraphQLProjectModel` by `list_field_table`); without it list
    expansions are counted as zero and callers should record an
    UnknownFact.
    """
    gql_ops = _operations(document, operation)
    depth = 0
    field_count = 0
    list_expansions = 0
    parents: set[str] = set()

    fragments = _fragments(document)

    def walk(
        sel_set: Any, parent_type: str | None, level: int, seen: frozenset[str]
    ) -> None:
        nonlocal depth, field_count, list_expansions
        if sel_set is None:
            return
        depth = max(depth, level)
        for sel in sel_set.selections:
            kind = sel.__class__.__name__
            if kind == "FieldNode":
                field_count += 1
                if parent_type:
                    parents.add(parent_type)
                is_list = (
                    schema_types.get(parent_type or "", {}).get(sel.name.value, False)
                    if schema_types
                    else False
                )
                if is_list:
                    list_expansions += 1
                child_type = (
                    schema_types.get(parent_type or "", {}).get(
                        f"{sel.name.value}#type"
                    )
                    if schema_types
                    else None
                )
                walk(sel.selection_set, child_type, level + 1, seen)
            elif kind == "InlineFragmentNode":
                tname = (
                    sel.type_condition.name.value if sel.type_condition else parent_type
                )
                walk(sel.selection_set, tname, level, seen)
            elif kind == "FragmentSpreadNode":
                frag = fragments.get(sel.name.value)
                if frag is not None and sel.name.value not in seen:
                    tname = (
                        frag.type_condition.name.value
                        if frag.type_condition
                        else parent_type
                    )
                    walk(frag.selection_set, tname, level, seen | {sel.name.value})

    for op in gql_ops:
        kind = _kind_str(op.operation)  # 'query' | 'mutation' | 'subscription'
        root: str | None = kind.capitalize()
        if model is not None:
            for t in model.types:
                if t.operation_root is not None and t.operation_root.value == kind:
                    root = t.name
                    break
        walk(op.selection_set, root, 1, frozenset())

    complexity = field_count + list_expansions * depth
    return GraphQLQueryShape(
        depth=depth,
        field_count=field_count,
        list_expansions=list_expansions,
        resolver_count=len(parents),
        estimated_complexity=complexity,
    )


def _operations(document: Any, operation_name: Any) -> list[Any]:
    ops = [
        d
        for d in document.definitions
        if d.__class__.__name__ == "OperationDefinitionNode"
    ]
    if operation_name is not None:
        ops = [o for o in ops if (o.name and o.name.value) == operation_name]
    return ops


def _fragments(document: Any) -> dict[str, Any]:
    return {
        d.name.value: d
        for d in document.definitions
        if d.__class__.__name__ == "FragmentDefinitionNode"
    }


def _kind_str(op: Any) -> str:
    return str(getattr(op, "value", op)).lower()


def list_field_table(model: GraphQLProjectModel) -> dict[str, dict[str, Any]]:
    """Map Type -> {field: is_list, 'field#type': named child type}."""
    table: dict[str, dict[str, Any]] = {}
    for t in model.types:
        entry: dict[str, Any] = {}
        for f in t.fields:
            entry[f.name] = f.type.is_list
            entry[f"{f.name}#type"] = f.type.name
        table[t.name] = entry
    return table
