"""PayloadShape (§148) + large-payload signal (§149) + serialization (§150).

Static schema shape is a candidate only; runtime confirmation comes
from observed response/request bytes on executions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_doctor_api.core.models import Model

LARGE_PAYLOAD_BYTES = 256 * 1024


@dataclass(frozen=True, kw_only=True)
class PayloadShape(Model):
    """§148 payload shape; `size` is None for static-only estimates."""

    size: int | None = None
    fields: int | None = None
    nesting: int | None = None
    collections: int | None = None
    content_type: str | None = None


def payload_shape_from_schema(schema: dict[str, Any] | None) -> PayloadShape:
    """Static §148 shape from a JSON-schema-like dict (bounded walk)."""
    if not isinstance(schema, dict):
        return PayloadShape()
    fields = 0
    collections = 0
    max_depth = 0
    stack: list[tuple[dict[str, Any], int, frozenset[int]]] = [
        (schema, 1, frozenset())
    ]
    while stack:
        node, depth, seen = stack.pop()
        if id(node) in seen or depth > 32:
            continue
        seen = seen | {id(node)}
        max_depth = max(max_depth, depth)
        if node.get("type") == "array" or "items" in node:
            collections += 1
        props = node.get("properties")
        if isinstance(props, dict):
            fields += len(props)
            for sub in props.values():
                if isinstance(sub, dict):
                    stack.append((sub, depth + 1, seen))
        for comp in ("allOf", "oneOf", "anyOf"):
            for sub in node.get(comp) or []:
                if isinstance(sub, dict):
                    stack.append((sub, depth + 1, seen))
        items = node.get("items")
        if isinstance(items, dict):
            stack.append((items, depth + 1, seen))
    return PayloadShape(fields=fields, nesting=max_depth, collections=collections)


def payload_shape_from_bytes(size: int) -> PayloadShape:
    return PayloadShape(size=size)


def is_large(shape: PayloadShape) -> bool | None:
    """Large-payload verdict; None when no size evidence exists."""
    if shape.size is not None:
        return shape.size >= LARGE_PAYLOAD_BYTES
    if shape.fields is not None and shape.fields >= 100:
        return None  # static candidate only - needs runtime confirmation
    return None
