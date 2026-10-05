"""Client scan orchestration (§17): file selection + per-language extractors."""

from __future__ import annotations

from collections.abc import Sequence

from forge_doctor_api.analyzers.clients.graphql_doc import (
    scan_graphql_document,
)
from forge_doctor_api.analyzers.clients.java import scan_java_source
from forge_doctor_api.analyzers.clients.javascript import scan_javascript_source
from forge_doctor_api.analyzers.clients.model import ApiClientModel, ClientCallSite
from forge_doctor_api.analyzers.clients.python import scan_python_source
from forge_doctor_api.analyzers.routes.adapter import is_skippable
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import UnknownFact

_PY = (".py",)
_JS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_JAVA = (".java",)
_GQL = (".graphql", ".gql")


def scan_clients(
    context: ProjectContext, paths: Sequence[str]
) -> ApiClientModel:
    """Scan project files for HTTP client call sites.

    Files are routed by extension; vendored/generated directories are skipped
    (§100). Unreadable or unparseable files produce no call sites.
    """
    sites: list[ClientCallSite] = []
    unknowns: list[UnknownFact] = []
    for relative in sorted(paths):
        if is_skippable(relative):
            continue
        lower = relative.lower()
        if lower.endswith(_PY):
            extractor = scan_python_source
        elif lower.endswith(_JS):
            extractor = scan_javascript_source
        elif lower.endswith(_JAVA):
            extractor = scan_java_source
        elif lower.endswith(_GQL):
            extractor = scan_graphql_document
        else:
            continue
        try:
            source = context.read_text(relative)
        except Exception:
            unknowns.append(
                UnknownFact(
                    subject=relative,
                    missing="file contents",
                    resolution="file could not be read as text",
                )
            )
            continue
        found, unknown = extractor(relative, source)
        sites.extend(found)
        unknowns.extend(unknown)
    ordered = tuple(
        sorted(
            sites,
            key=lambda s: (s.client, s.location.path, s.location.line, s.method or ""),
        )
    )
    return ApiClientModel(
        clients=tuple(sorted({s.client for s in ordered})),
        call_sites=ordered,
        unknowns=tuple(sorted(unknowns, key=lambda u: (u.subject, u.missing))),
    )
