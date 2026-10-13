"""`ApiClientModel` (§17) — known API consumers found in source code.

Pure static evidence: `requests`/`httpx` in Python, `fetch`/`axios` in
JS/TS (spec 009 scope). Every `ClientCallSite` records the HTTP method and
URL *only* when they are statically literal — dynamic constructions land in
`ClientScan.unknowns` and are never guessed (§101, §183).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.core.models import Model, SourceLocation, UnknownFact


class ClientLanguage(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    JAVA = "java"
    GRAPHQL = "graphql"


@dataclass(frozen=True, kw_only=True)
class ClientCallSite(Model):
    """One HTTP client call.

    - `client`: consuming service/module identity (source-tree grouping).
    - `library`: `requests` | `httpx` | `fetch` | `axios`.
    - `method`/`url`: literal evidence; `None` when dynamic (§101).
    - `path`: path portion derived from `url` when it parses.
    - `operation`: invoked operation identity for non-HTTP call sites —
      generated OpenAPI client method name (operationId), gRPC stub
      method, GraphQL operation name. `None` when not statically known.
    - `response_fields`: field names statically read off the response —
      the evidence that upgrades a change to confirmed impact (§183).
    """

    client: str
    language: ClientLanguage
    library: str
    method: str | None
    url: str | None
    path: str | None
    operation: str | None = None
    response_fields: tuple[str, ...] = ()
    location: SourceLocation


@dataclass(frozen=True, kw_only=True)
class ClientScan(Model):
    """Result of scanning one source tree for client call sites."""

    call_sites: tuple[ClientCallSite, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ApiClientModel(Model):
    """§17 client model: known consumers, call sites, field usage, unknowns."""

    clients: tuple[str, ...] = ()
    call_sites: tuple[ClientCallSite, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    def consumers(self, method: str | None, paths: frozenset[str]) -> tuple[ClientCallSite, ...]:
        """Call sites whose method+path match any of `paths` (normalized)."""
        return tuple(
            s
            for s in self.call_sites
            if s.path is not None
            and s.path in paths
            and (method is None or s.method is None or s.method == method)
        )


def client_name_for(path: str) -> str:
    """Client identity = top-level directory, else the file stem."""
    parts = path.split("/")
    if len(parts) > 1:
        return parts[0]
    stem = parts[0].rsplit(".", 1)[0]
    return stem or "client"
