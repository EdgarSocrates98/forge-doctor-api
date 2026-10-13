"""YAML/JSON loading with source locations (§10.1).

Documents are parsed into plain JSON-compatible values (dict, list, str, int,
float, bool, None) plus a map from JSON pointer to 1-based (line, column).
Loading never raises on bad input: every failure becomes a `LoadIssue`.

Hardening:

- YAML is composed with `SafeLoader` (no arbitrary tags/objects);
- implicit timestamps stay strings so values remain JSON-compatible;
- mapping keys keep their source text (`200:` stays `"200"`);
- YAML merge keys (`<<`) are resolved like PyYAML does;
- recursive aliases (`&a [*a]`) and nesting deeper than `MAX_DEPTH` are
  rejected; total alias expansion is bounded by `MAX_NODES`, so exponential
  ("billion laughs") aliases are rejected instead of hanging;
- the tree is walked iteratively, so deep nesting cannot crash the walker;
- non-finite numbers (`.inf`, `1e999`) are kept as their source text.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

MAX_NODES = 250_000
MAX_DEPTH = 256
_COLLECTION_TAGS = frozenset({"tag:yaml.org,2002:seq", "tag:yaml.org,2002:map"})

Locations = dict[str, tuple[int, int]]


class _Loader(yaml.SafeLoader):
    """SafeLoader without the implicit timestamp resolver."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass(frozen=True)
class LoadIssue:
    code: str
    message: str
    line: int | None = None
    column: int | None = None


@dataclass
class LoadedDocument:
    value: Any = None
    locations: Locations = field(default_factory=dict)
    issues: list[LoadIssue] = field(default_factory=list)
    ok: bool = True


class _LoadError(Exception):
    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column


def escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _child(pointer: str, token: str) -> str:
    return f"{pointer}/{escape_pointer_token(token)}"


def _mark(node: Node) -> tuple[int, int]:
    return node.start_mark.line + 1, node.start_mark.column + 1


def _scalar(loader: _Loader, node: ScalarNode) -> Any:
    value = loader.construct_object(node)
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else node.value
    return node.value


def _check_graph(root: Node) -> None:
    """Reject recursive aliases (`&a [*a]`) and over-deep nesting before expansion."""
    state: dict[int, int] = {}  # node id -> 1 (on current path) | 2 (done)
    stack: list[tuple[Node, int, bool]] = [(root, 1, False)]
    while stack:
        node, depth, leaving = stack.pop()
        if leaving:
            state[id(node)] = 2
            continue
        if depth > MAX_DEPTH:
            line, column = _mark(node)
            raise _LoadError(f"document nesting exceeds {MAX_DEPTH} levels", line, column)
        mark = state.get(id(node))
        if mark == 1:
            line, column = _mark(node)
            raise _LoadError("recursive YAML alias", line, column)
        if mark == 2 or isinstance(node, ScalarNode):
            continue
        state[id(node)] = 1
        stack.append((node, depth, True))
        if isinstance(node, SequenceNode):
            stack.extend((child, depth + 1, False) for child in node.value)
        elif isinstance(node, MappingNode):
            for key_node, value_node in node.value:
                stack.append((key_node, depth + 1, False))
                stack.append((value_node, depth + 1, False))


def _build(loader: _Loader, root: Node, issues: list[LoadIssue]) -> tuple[Any, Locations]:
    """Convert a composed YAML node tree iteratively, recording locations."""
    locations: Locations = {"": _mark(root)}
    budget = MAX_NODES
    holder: list[Any] = [None]
    # Each frame: (node, pointer, container, slot) — store result in container[slot].
    stack: list[tuple[Node, str, Any, Any]] = [(root, "", holder, 0)]
    while stack:
        node, pointer, container, slot = stack.pop()
        budget -= 1
        if budget < 0:
            raise _LoadError(
                f"document exceeds {MAX_NODES} nodes (recursive or exponential YAML aliases?)"
            )
        if isinstance(node, ScalarNode):
            container[slot] = _scalar(loader, node)
        elif node.tag not in _COLLECTION_TAGS:
            line, column = _mark(node)
            raise _LoadError(f"unsupported YAML tag {node.tag!r}", line, column)
        elif isinstance(node, SequenceNode):
            items: list[Any] = [None] * len(node.value)
            container[slot] = items
            for index in reversed(range(len(node.value))):
                item = node.value[index]
                item_pointer = _child(pointer, str(index))
                locations[item_pointer] = _mark(item)
                stack.append((item, item_pointer, items, index))
        elif isinstance(node, MappingNode):
            mapping: dict[str, Any] = {}
            container[slot] = mapping
            seen: set[str] = set()
            for key_node, _ in node.value:
                if isinstance(key_node, ScalarNode) and key_node.tag != "tag:yaml.org,2002:merge":
                    key = str(key_node.value)
                    if key in seen:
                        line, column = _mark(key_node)
                        issues.append(
                            LoadIssue(
                                "DUPLICATE_KEY",
                                f"duplicate key {key!r} at {pointer or '/'}",
                                line,
                                column,
                            )
                        )
                    seen.add(key)
            loader.flatten_mapping(node)  # resolves YAML merge keys ('<<')
            children: list[tuple[Node, str, str]] = []
            for key_node, value_node in node.value:
                if not isinstance(key_node, ScalarNode):
                    line, column = _mark(key_node)
                    raise _LoadError("mapping keys must be scalars", line, column)
                key = str(key_node.value)
                child_pointer = _child(pointer, key)
                if key not in mapping:
                    children.append((value_node, child_pointer, key))
                else:
                    children = [c for c in children if c[2] != key]
                    children.append((value_node, child_pointer, key))
                mapping[key] = None
                locations[child_pointer] = _mark(key_node)
            for value_node, child_pointer, key in reversed(children):
                stack.append((value_node, child_pointer, mapping, key))
        else:  # pragma: no cover - PyYAML only produces the three node kinds
            raise _LoadError(f"unsupported YAML node {type(node).__name__}")
    return holder[0], locations


def _compose(text: str) -> tuple[_Loader, Node | None]:
    loader = _Loader(text)
    try:
        return loader, loader.get_single_node()
    finally:
        loader.dispose()


def _yaml_error(exc: yaml.YAMLError) -> _LoadError:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    if mark is None:
        return _LoadError(f"malformed YAML: {problem}")
    return _LoadError(f"malformed YAML: {problem}", mark.line + 1, mark.column + 1)


def load_yaml(text: str) -> LoadedDocument:
    result = LoadedDocument()
    try:
        loader, node = _compose(text)
        if node is None:
            return result
        _check_graph(node)
        result.value, result.locations = _build(loader, node, result.issues)
    except yaml.YAMLError as exc:
        error = _yaml_error(exc)
        result.issues.append(LoadIssue("MALFORMED", error.message, error.line, error.column))
        result.ok = False
    except _LoadError as exc:
        result.issues.append(LoadIssue("MALFORMED", exc.message, exc.line, exc.column))
        result.ok = False
    except RecursionError:
        result.issues.append(LoadIssue("MALFORMED", "document nesting is too deep"))
        result.ok = False
    if not result.ok:
        result.value, result.locations = None, {}
    return result


def _depth(value: Any) -> int:
    deepest = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, dict | list):
            deepest = max(deepest, depth)
            children = current.values() if isinstance(current, dict) else current
            stack.extend((child, depth + 1) for child in children)
    return deepest


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def _number(text: str) -> Any:
    value = float(text)
    return value if math.isfinite(value) else text


def load_json(text: str) -> LoadedDocument:
    """Parse strict JSON; locations come from a best-effort YAML composition."""
    result = LoadedDocument()
    duplicates: list[str] = []

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for key, value in items:
            if key in mapping:
                duplicates.append(key)
            mapping[key] = value
        return mapping

    try:
        result.value = json.loads(
            text, object_pairs_hook=pairs, parse_constant=_reject_constant, parse_float=_number
        )
    except json.JSONDecodeError as exc:
        result.issues.append(
            LoadIssue("MALFORMED", f"malformed JSON: {exc.msg}", exc.lineno, exc.colno)
        )
        result.ok = False
        return result
    except (ValueError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "document nesting is too deep"
        result.issues.append(LoadIssue("MALFORMED", f"malformed JSON: {message}"))
        result.ok = False
        return result
    if _depth(result.value) > MAX_DEPTH:
        result.issues.append(LoadIssue("MALFORMED", f"document nesting exceeds {MAX_DEPTH} levels"))
        result.ok = False
        result.value = None
        return result
    shadow = load_yaml(text)
    if shadow.ok:
        result.locations = shadow.locations
    result.issues.extend(
        LoadIssue("DUPLICATE_KEY", f"duplicate key {key!r}") for key in sorted(set(duplicates))
    )
    return result


def load_document(text: str, fmt: str) -> LoadedDocument:
    return load_json(text) if fmt == "json" else load_yaml(text)
