"""Bundled OpenAPI knowledge facade (§10, §128, §129).

Facts live in `knowledge/openapi/versions.yaml` — this module only
re-exports them in the shape the parser needs. Never fetched live.
"""

from __future__ import annotations

import re
from typing import Any

from forge_doctor_api.knowledge.loader import load_pack

_PACK = load_pack("openapi", "versions.yaml")
KNOWLEDGE_PACK_VERSION = _PACK.edition


def _family_fields(family: str) -> dict[str, Any]:
    entry = _PACK.entry(f"openapi-{family}")
    return entry.fields if entry is not None else {}


SUPPORTED_FAMILIES: tuple[str, ...] = tuple(
    e.fields["family"]
    for e in _PACK.entries
    if e.fields.get("supported") is True and isinstance(e.fields["family"], str)
)

KNOWN_RELEASES: tuple[str, ...] = tuple(
    release
    for e in _PACK.entries
    if e.fields.get("supported") is True
    for release in e.fields.get("releases", ())
    if isinstance(release, str)
)

HTTP_METHODS: tuple[str, ...] = tuple(
    m for m in _family_fields("3.0").get("http_methods", ())
    if isinstance(m, str)
)
# OpenAPI 3.2 adds `query` and `additionalOperations` (custom methods).
HTTP_METHODS_3_2: tuple[str, ...] = tuple(
    m for m in _family_fields("3.2").get("http_methods", ())
    if isinstance(m, str)
)

VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?$"
)


def version_family(version: str) -> str | None:
    """Return `MAJOR.MINOR` when `version` is a well-formed supported release."""
    match = VERSION_PATTERN.match(version)
    if match is None:
        return None
    family = f"{match['major']}.{match['minor']}"
    return family if family in SUPPORTED_FAMILIES else None
