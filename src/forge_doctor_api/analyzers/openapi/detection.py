"""OpenAPI detection gate (§100, §101).

A document is treated as OpenAPI only when its root mapping carries the
strong `openapi` marker. `paths`, `info`, `components` or a file named
`openapi.yml` are weak markers and never suffice on their own. Swagger 2.0
(`swagger:` root key) is recognized but reported as unsupported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_doctor_api.analyzers.openapi.knowledge import (
    SUPPORTED_FAMILIES,
    VERSION_PATTERN,
    version_family,
)
from forge_doctor_api.analyzers.openapi.model import DocumentStatus


@dataclass(frozen=True)
class Detection:
    status: DocumentStatus
    version: str | None = None
    family: str | None = None
    reason: str = ""


def detect_openapi(value: Any) -> Detection:
    """Classify a parsed document by its root markers. Never raises."""
    if not isinstance(value, dict):
        return Detection(DocumentStatus.NOT_OPENAPI, reason="root is not a mapping")
    if "openapi" not in value:
        if "swagger" in value:
            raw = value["swagger"]
            return Detection(
                DocumentStatus.UNSUPPORTED_VERSION,
                version=raw if isinstance(raw, str) else None,
                reason=f"Swagger/OpenAPI 2.0 is not supported: swagger={raw!r}",
            )
        return Detection(DocumentStatus.NOT_OPENAPI, reason="missing root 'openapi' field")
    raw = value["openapi"]
    if not isinstance(raw, str):
        return Detection(
            DocumentStatus.INVALID_VERSION,
            reason=f"'openapi' must be a string like '3.1.0', got {type(raw).__name__} {raw!r}",
        )
    if VERSION_PATTERN.match(raw) is None:
        return Detection(
            DocumentStatus.INVALID_VERSION,
            version=raw,
            reason=f"'openapi' is not a MAJOR.MINOR.PATCH version: {raw!r}",
        )
    family = version_family(raw)
    if family is None:
        supported = ", ".join(f"{f}.x" for f in SUPPORTED_FAMILIES)
        return Detection(
            DocumentStatus.UNSUPPORTED_VERSION,
            version=raw,
            reason=f"unsupported OpenAPI version {raw!r} (supported: {supported})",
        )
    return Detection(DocumentStatus.PARSED, version=raw, family=family)
