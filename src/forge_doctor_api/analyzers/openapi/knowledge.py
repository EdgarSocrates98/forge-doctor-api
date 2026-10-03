"""Bundled OpenAPI knowledge pack (§10, §128, §129).

Versioned with the tool and never fetched at scan time. Adding a family
(e.g. a future 3.3) is a code change reviewed like any other.
"""

from __future__ import annotations

import re

KNOWLEDGE_PACK_VERSION = "2026.09"

SUPPORTED_FAMILIES: tuple[str, ...] = ("3.0", "3.1", "3.2")

# Published patch releases known to this pack. Unknown patches inside a
# supported family are still accepted: patch releases do not change structure.
KNOWN_RELEASES: tuple[str, ...] = (
    "3.0.0",
    "3.0.1",
    "3.0.2",
    "3.0.3",
    "3.0.4",
    "3.1.0",
    "3.1.1",
    "3.1.2",
    "3.2.0",
    "3.2.1",
)

HTTP_METHODS: tuple[str, ...] = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
)
# OpenAPI 3.2 adds `query` and `additionalOperations` (custom methods).
HTTP_METHODS_3_2: tuple[str, ...] = (*HTTP_METHODS, "query")

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
