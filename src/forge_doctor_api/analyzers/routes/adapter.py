"""`FrameworkAdapter` contract (§192).

Every framework adapter must implement the §192 capabilities:

- `attribution gate` — `attribute()`: decides, per file, whether the
  framework is genuinely in play. Requires multiple strong markers (§101);
  decorator-shaped text in comments/strings never parses into `ast`, so it
  cannot attribute.
- `route discovery` — `scan()`: emits `RouteModel`s for attributed files.
- `auth discovery` — auth-relevant dependency names land on
  `RouteModel.auth` (evidence, never inferred policy).
- `schema discovery` — `RouteModel.request_schema`/`response_schema` when
  statically resolvable.
- `source location` — every route/attribution carries `SourceLocation`.
- `adversarial tests` — each adapter ships §100-style fixtures.

Adapters never import or execute target code (§1): analysis is `ast`-only,
and all filesystem access goes through `ProjectContext` (§203).
"""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from forge_doctor_api.analyzers.routes.model import (
    Attribution,
    RouteModel,
    RouteScan,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import SourceLocation, UnknownFact

# Directories whose content is not source evidence: vendored or generated
# code never counts as an implementation (§100 adversarial posture).
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "site-packages",
        "dist",
        "build",
        "generated",
        "_generated",
    }
)


def is_skippable(relative: str) -> bool:
    return any(part in SKIP_DIRS for part in relative.split("/"))


@dataclass(frozen=True)
class ParsedFile:
    """One source file that passed the adapter's attribution gate."""

    path: str
    source: str
    tree: ast.Module
    attribution: Attribution


def module_name(relative: str) -> str:
    """`routers/items.py` -> `routers.items` (init files map to their package)."""
    stem = relative[:-3] if relative.endswith(".py") else relative
    parts = [p for p in stem.split("/") if p]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class FrameworkAdapter(ABC):
    """Static, `ast`-only adapter. `framework` is the evidence domain tag."""

    name: str
    framework: str
    file_pattern: str = "**/*.py"

    @abstractmethod
    def attribute(self, tree: ast.Module, path: str) -> Attribution | None:
        """Attribution gate. `None` means this file is not the framework."""

    @abstractmethod
    def scan(
        self, context: ProjectContext, service: str, paths: Sequence[str] | None = None
    ) -> RouteScan:
        """Full pipeline: attribute each source file, then extract routes."""

    def parse_files(
        self, context: ProjectContext, paths: Sequence[str] | None, unknowns: list[UnknownFact]
    ) -> Iterator[ParsedFile]:
        """Hermetic read + `ast.parse` + attribution gate, in sorted order."""
        files = list(paths) if paths is not None else list(context.iter_files(self.file_pattern))
        for relative in sorted(files):
            if is_skippable(relative) or not relative.endswith(".py"):
                continue
            try:
                source = context.read_text(relative)
            except Exception:
                unknowns.append(
                    UnknownFact(
                        subject=relative,
                        missing="file contents",
                        resolution="restore read access or remove the file",
                    )
                )
                continue
            try:
                tree = ast.parse(source, filename=relative)
            except SyntaxError:
                unknowns.append(
                    UnknownFact(
                        subject=relative,
                        missing="parseable Python",
                        resolution="file does not parse with ast; routes cannot be evidenced",
                    )
                )
                continue
            attribution = self.attribute(tree, relative)
            if attribution is not None:
                yield ParsedFile(relative, source, tree, attribution)


def route_key(route: RouteModel) -> tuple[str, str, str, int]:
    loc: SourceLocation = route.source_location
    return (route.method, route.path, route.handler, loc.line or 0)
