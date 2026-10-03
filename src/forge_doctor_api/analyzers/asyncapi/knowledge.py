"""Bundled AsyncAPI knowledge facade (§20, §128, §129).

AsyncAPI 2.x uses channel `publish`/`subscribe` verbs; 3.x uses operations
with `action: send|receive`. Both normalize into one `AsyncApiModel` —
`send` means the application produces onto the channel, `receive` means it
consumes from it. Facts live in `knowledge/asyncapi/versions.yaml`.
"""

from __future__ import annotations

import re

from forge_doctor_api.knowledge.loader import load_pack

_PACK = load_pack("asyncapi", "versions.yaml")
KNOWLEDGE_PACK_VERSION = _PACK.edition


def _families(*entry_ids: str) -> tuple[str, ...]:
    out: list[str] = []
    for entry_id in entry_ids:
        entry = _PACK.entry(entry_id)
        if entry is not None:
            out.extend(
                f for f in entry.fields.get("families", ())
                if isinstance(f, str)
            )
    return tuple(out)


SUPPORTED_FAMILIES: tuple[str, ...] = _families("asyncapi-2", "asyncapi-3")

KNOWN_RELEASES: tuple[str, ...] = tuple(
    release
    for entry_id in ("asyncapi-2", "asyncapi-3")
    if (entry := _PACK.entry(entry_id)) is not None
    for release in entry.fields.get("releases", ())
    if isinstance(release, str)
)

VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?$"
)

# Broker protocols this pack recognizes as binding evidence.
_bindings = _PACK.entry("bindings")
KNOWN_BINDINGS: tuple[str, ...] = (
    tuple(p for p in _bindings.fields.get("protocols", ()) if isinstance(p, str))
    if _bindings is not None
    else ()
)


def version_family(version: str) -> str | None:
    match = VERSION_PATTERN.match(version)
    if match is None:
        return None
    family = f"{match['major']}.{match['minor']}"
    return family if family in SUPPORTED_FAMILIES else None
