"""`$ref` classification, JSON pointer lookup, and cycle detection (§10.2, §10.3).

Nothing here recurses over user data: pointer lookup is a loop, and cycle
detection is an iterative Tarjan SCC over the reference graph, so cyclic or
very deep reference chains cannot overflow the stack.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from posixpath import dirname, join, normpath
from typing import Any

from forge_doctor_api.analyzers.openapi.model import RefStatus

_PERCENT = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_MISSING = object()


@dataclass(frozen=True)
class RefTarget:
    """Where a reference points. `path` is project-relative POSIX; `pointer` is a JSON pointer."""

    status: RefStatus
    path: str | None = None
    pointer: str | None = None
    reason: str = ""


def unquote(text: str) -> str:
    """Decode RFC 3986 percent-escapes (UTF-8); local so the package has no `urllib` import."""
    return _PERCENT.sub(
        lambda m: bytes.fromhex(m[0].replace("%", "")).decode("utf-8", "replace"), text
    )


def split_pointer(pointer: str) -> list[str] | None:
    """Decode a JSON pointer (`/a~1b/0`) into tokens; None when malformed."""
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        return None
    tokens = pointer[1:].split("/")
    if any(re.search(r"~(?![01])", token) for token in tokens):
        return None
    return [token.replace("~1", "/").replace("~0", "~") for token in tokens]


def lookup(value: Any, pointer: str) -> Any:
    """Follow a JSON pointer through parsed data; `_MISSING`-safe, returns None-sentinel."""
    tokens = split_pointer(pointer)
    if tokens is None:
        return _MISSING
    current = value
    for token in tokens:
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, Sequence) and not isinstance(current, str):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return _MISSING
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def is_missing(value: Any) -> bool:
    return value is _MISSING


def classify(ref: object, base_path: str) -> RefTarget:
    """Resolve a `$ref` string syntactically against the referring document path.

    Remote URLs and any other URI scheme are EXTERNAL (recorded, never
    fetched). Absolute or root-escaping file paths are OUTSIDE_ROOT (never read).
    """
    if not isinstance(ref, str) or not ref.strip():
        return RefTarget(RefStatus.INVALID, reason="$ref must be a non-empty string")
    if _SCHEME.match(ref):
        return RefTarget(RefStatus.EXTERNAL, reason="remote or non-file URI; not fetched")
    if ref.startswith("//"):
        return RefTarget(RefStatus.EXTERNAL, reason="network-path reference; not fetched")
    file_part, _, fragment = ref.partition("#")
    pointer = unquote(fragment)
    if split_pointer(pointer) is None:
        return RefTarget(RefStatus.INVALID, reason=f"malformed JSON pointer {fragment!r}")
    if not file_part:
        return RefTarget(RefStatus.RESOLVED, path=base_path, pointer=pointer)
    file_part = unquote(file_part).split("?", 1)[0]
    if file_part.startswith("/") or "\\" in file_part:
        return RefTarget(RefStatus.OUTSIDE_ROOT, reason="absolute or non-POSIX file reference")
    target = normpath(join(dirname(base_path), file_part))
    if target == ".." or target.startswith("../"):
        return RefTarget(RefStatus.OUTSIDE_ROOT, reason="file reference escapes the project root")
    return RefTarget(RefStatus.RESOLVED, path=target, pointer=pointer)


def within(pointer: str, container: str) -> bool:
    return container == "" or pointer == container or pointer.startswith(container + "/")


def strongly_connected(nodes: Sequence[str], edges: Mapping[str, Sequence[str]]) -> list[list[str]]:
    """Iterative Tarjan. Returns SCCs that form cycles (size > 1 or self-loop), sorted."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0
    for start in sorted(nodes):
        if start in index:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            successors = sorted(edges.get(node, ()))
            if child < len(successors):
                work.append((node, child + 1))
                nxt = successors[child]
                if nxt not in index:
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            if low[node] == index[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1 or node in edges.get(node, ()):
                    result.append(sorted(component))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return sorted(result)
