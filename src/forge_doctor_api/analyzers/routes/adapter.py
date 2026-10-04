"""`FrameworkAdapter` contract (§38-§41, §192).

Two layers, deliberately separate:

- `FrameworkAdapter` — the language-neutral §39 protocol every adapter
  must satisfy: `attribute`, `discover_routes`, `discover_auth`,
  `discover_schemas`, `discover_dependencies`, `discover_middleware`,
  `discover_error_handlers`, `discover_validation`,
  `discover_serialization`, `discover_client_calls`. Each `discover_*`
  returns `SurfaceResult`; an unanswerable surface returns empty items
  PLUS an `UnknownFact` — never a fabricated zero.

- `AstFrameworkAdapter` — the Python `ast` base class carrying the
  spec-006 machinery (per-file attribution gate, hermetic parse,
  `parse_files`). Language adapters whose source is not Python (Java,
  JS/TS) implement `FrameworkAdapter` directly over the
  comment/string-stripped scanner in `textscan.py`.

Adapters never import or execute target code (§1): analysis is static
only, and all filesystem access goes through `ProjectContext` (§203).
"""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from forge_doctor_api.analyzers.routes.model import (
    Attribution,
    RouteModel,
    RouteScan,
    SurfaceResult,
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


def unknown_surface(surface: str, framework: str) -> SurfaceResult:
    """§39 unanswerable surface: empty items + the explicit gap."""
    return SurfaceResult(
        surface=surface,
        unknowns=(
            UnknownFact(
                subject=f"{framework} {surface}",
                missing=f"static {surface} evidence",
                resolution=(
                    "the adapter found no extractable evidence for this "
                    "surface; absence is not a claim of absence"
                ),
            ),
        ),
    )


@runtime_checkable
class FrameworkAdapter(Protocol):
    """§39 language-neutral adapter contract (spec 050).

    `detect` is the cheap gate (manifest/import strong markers);
    `attribute` is the per-file evidence gate. Every `discover_*`
    returns `SurfaceResult` — sorted items, unknowns when unanswerable.
    """

    name: str
    framework: str

    def detect(self, context: ProjectContext, files: Sequence[str]) -> bool:
        """Strong-marker gate: is this framework genuinely in play?"""
        ...

    def attribute(
        self, context: ProjectContext, files: Sequence[str]
    ) -> tuple[Attribution, ...]:
        """Per-file framework attributions with evidence."""
        ...

    def discover_routes(
        self,
        context: ProjectContext,
        service: str,
        files: Sequence[str] | None = None,
    ) -> RouteScan:
        """RouteModels for attributed files."""
        ...

    def discover_auth(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Auth-relevant evidence (decorators, deps, guards)."""
        ...

    def discover_schemas(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Request/response schema candidate names + locations."""
        ...

    def discover_dependencies(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Injected/depended-upon components."""
        ...

    def discover_middleware(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Middleware registrations applying to routes."""
        ...

    def discover_error_handlers(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Exception/error handler registrations."""
        ...

    def discover_validation(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Validation constraints on inputs."""
        ...

    def discover_serialization(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Serialization shaping (response models, encoders)."""
        ...

    def discover_client_calls(
        self, context: ProjectContext, files: Sequence[str]
    ) -> SurfaceResult:
        """Outbound HTTP client calls inside route code."""
        ...


class AstFrameworkAdapter(ABC):
    """Static, `ast`-only adapter. `framework` is the evidence domain tag."""

    name: str
    framework: str
    file_pattern: str = "**/*.py"

    @abstractmethod
    def attribute_tree(self, tree: ast.Module, path: str) -> Attribution | None:
        """Attribution gate. `None` means this file is not the framework."""

    @abstractmethod
    def scan(
        self, context: ProjectContext, service: str, paths: Sequence[str] | None = None
    ) -> RouteScan:
        """Full pipeline: attribute each source file, then extract routes."""

    # -- §39 protocol defaults -------------------------------------------------

    def attribute(
        self, context: ProjectContext, files: Sequence[str]
    ) -> tuple[Attribution, ...]:
        """Concrete §39 attribution: the ast gate, per file, sorted."""
        unknowns: list[UnknownFact] = []
        attrs = {
            pf.attribution
            for pf in self.parse_files(context, files, unknowns)
        }
        return tuple(sorted(attrs, key=lambda a: a.path))

    def detect(self, context: ProjectContext, files: Sequence[str]) -> bool:
        """Python default: any file passing the attribution gate."""
        return bool(self.attribute(context, files))

    def discover_routes(
        self,
        context: ProjectContext,
        service: str,
        files: Sequence[str] | None = None,
    ) -> RouteScan:
        """§39 alias for `scan`."""
        return self.scan(context, service, files)

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
            attribution = self.attribute_tree(tree, relative)
            if attribution is not None:
                yield ParsedFile(relative, source, tree, attribution)


def route_key(route: RouteModel) -> tuple[str, str, str, int]:
    loc: SourceLocation = route.source_location
    return (route.method, route.path, route.handler, loc.line or 0)


def available_adapters(
    context: ProjectContext,
    files: Sequence[str],
) -> tuple[FrameworkAdapter, ...]:
    """Builtin adapters whose `detect()` matches this project.

    Ordered by adapter name for determinism; an unknown framework
    simply yields no adapter — the caller records the unknown, the
    adapter never guesses (§41).
    """
    # Local imports keep adapter modules (and their scanners) out of the
    # base import graph — the registry itself is dependency-free.
    from forge_doctor_api.analyzers.routes.fastapi import FastApiAdapter
    from forge_doctor_api.analyzers.routes.javascript import (
        ExpressAdapter,
        NestJsAdapter,
    )
    from forge_doctor_api.analyzers.routes.spring import SpringBootAdapter

    adapters: list[FrameworkAdapter] = [
        FastApiAdapter(), ExpressAdapter(), NestJsAdapter(),
        SpringBootAdapter(),
    ]
    return tuple(
        sorted(
            (a for a in adapters if a.detect(context, files)),
            key=lambda a: a.name,
        )
    )
