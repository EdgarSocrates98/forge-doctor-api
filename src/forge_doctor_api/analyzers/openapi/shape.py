"""Deterministic shallow fingerprints for JSON Schema fragments.

`schema_shape` condenses a schema into a short comparable token so checks can
talk about "same-shaped" vs "different-shaped" payloads without retaining raw
schema content in the model. The fingerprint is deliberately shallow — it is
a comparison aid, never an identity.
"""

from __future__ import annotations

from typing import Any

_COMBINERS = ("allOf", "anyOf", "oneOf", "not")


def _tokens(values: Any) -> str:
    return ",".join(sorted(str(v) for v in values)) if isinstance(values, list | dict) else ""


def schema_shape(node: Any) -> str:
    """Return a deterministic shallow fingerprint of one schema fragment."""
    if isinstance(node, bool):
        return f"schema:{node}"
    if not isinstance(node, dict):
        return "schema:?"
    ref = node.get("$ref")
    if isinstance(ref, str):
        return f"ref:{ref}"
    parts: list[str] = []
    declared = node.get("type")
    if isinstance(declared, str):
        parts.append(f"type:{declared}")
    elif isinstance(declared, list):
        parts.append(f"type:{'|'.join(sorted(str(t) for t in declared))}")
    fmt = node.get("format")
    if isinstance(fmt, str):
        parts.append(f"fmt:{fmt}")
    for keyword in _COMBINERS:
        if isinstance(node.get(keyword), list | dict):
            parts.append(keyword)
    if "enum" in node:
        parts.append("enum")
    if "const" in node:
        parts.append("const")
    properties = node.get("properties")
    if isinstance(properties, dict):
        parts.append(f"props({_tokens(properties)})")
    if isinstance(node.get("items"), dict | bool):
        parts.append("items")
    if isinstance(node.get("required"), list):
        parts.append(f"req({_tokens(node['required'])})")
    additional = node.get("additionalProperties")
    if additional is True:
        parts.append("ap:free")
    elif additional is False:
        parts.append("ap:none")
    elif isinstance(additional, dict):
        parts.append("ap:schema")
    if isinstance(node.get("patternProperties"), dict):
        parts.append("pattern-props")
    return f"schema({';'.join(parts)})"


def content_schemas(node: Any) -> tuple[str, ...]:
    """Sorted shape fingerprints for every `content.{media}.schema` in `node`."""
    content = node.get("content") if isinstance(node, dict) else None
    if not isinstance(content, dict):
        return ()
    shapes: list[str] = []
    for media in sorted(content):
        entry = content[media]
        if isinstance(entry, dict) and "schema" in entry:
            shapes.append(schema_shape(entry["schema"]))
    return tuple(sorted(shapes))


def header_names(node: Any) -> tuple[str, ...]:
    headers = node.get("headers") if isinstance(node, dict) else None
    if not isinstance(headers, dict):
        return ()
    return tuple(sorted(str(name) for name in headers))
