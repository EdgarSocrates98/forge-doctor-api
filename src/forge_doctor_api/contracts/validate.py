"""Dependency-free ``forge-contracts/1`` schema validation.

Covers the contract surface: ``required`` keys (present and non-null),
``enum``, primitive ``type`` (string/integer/boolean/array/object,
``[T, "null"]`` unions), nested ``properties``/``items``, and
``additionalProperties``. ``x-*`` keys always pass — extensions are the
contract's forward-compat channel, not a violation.

This is deliberately *not* a general JSON Schema implementation — no
``$ref`` resolution, no ``pattern``/``format`` evaluation beyond
``contract_version`` family-major shape, no combinators. The contract
schemas only use what this validator checks.
"""

from __future__ import annotations

import re
from typing import Any

from forge_doctor_api.contracts.schemas import FORGE_CONTRACT_SCHEMAS

_VERSION_RE = re.compile(r"^forge-contracts/\d+$")

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: (
        isinstance(v, (int, float)) and not isinstance(v, bool)),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


class ContractError(ValueError):
    """A payload does not satisfy the forge-contracts/1 schema."""


def _check_type(value: Any, spec: dict[str, Any], path: str) -> None:
    declared = spec.get("type")
    if declared is None:
        return
    types = declared if isinstance(declared, list) else [declared]
    if not any(_TYPE_CHECKS.get(t, lambda v: False)(value)
               for t in types):
        raise ContractError(
            f"{path}: expected {'|'.join(map(str, types))}, "
            f"got {type(value).__name__}")


def _walk(value: Any, spec: dict[str, Any], path: str,
          errors: list[str]) -> None:
    try:
        _check_type(value, spec, path)
    except ContractError as exc:
        errors.append(str(exc))
        return
    if "enum" in spec and value not in spec["enum"]:
        errors.append(
            f"{path}: {value!r} not in enum {spec['enum']}")
        return
    if value is None:
        return
    if (spec.get("type") == "string" and spec.get("pattern")
            and path.endswith("contract_version")
            and not _VERSION_RE.match(str(value))):
        errors.append(f"{path}: {value!r} is not forge-contracts/<major>")
    if isinstance(value, dict):
        required = spec.get("required", ())
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: missing required field")
            elif value[key] is None:
                errors.append(
                    f"{path}.{key}: required field is explicitly null")
        props = spec.get("properties", {})
        for key, sub in value.items():
            if key.startswith("x-"):
                continue  # extension namespace always allowed
            sub_spec = props.get(key)
            if sub_spec is not None:
                _walk(sub, sub_spec, f"{path}.{key}", errors)
            elif spec.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unknown field")
    elif isinstance(value, list):
        item_spec = spec.get("items")
        if isinstance(item_spec, dict):
            for i, item in enumerate(value):
                _walk(item, item_spec, f"{path}[{i}]", errors)


def validate(payload: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Validate ``payload`` against a contract schema; return errors."""
    errors: list[str] = []
    _walk(payload, schema, "$", errors)
    return errors


def validate_named(payload: dict[str, Any], kind: str) -> list[str]:
    """Validate against a named contract schema (``finding``, ``handoff``…)."""
    schema = FORGE_CONTRACT_SCHEMAS.get(kind)
    if schema is None:
        raise ContractError(f"unknown contract schema: {kind!r}")
    return validate(payload, schema)


def assert_valid(payload: dict[str, Any], kind: str) -> None:
    """Raise ``ContractError`` listing every violation."""
    errors = validate_named(payload, kind)
    if errors:
        raise ContractError(
            f"{kind} payload violates forge-contracts/1:\n"
            + "\n".join(f"  {e}" for e in errors))
