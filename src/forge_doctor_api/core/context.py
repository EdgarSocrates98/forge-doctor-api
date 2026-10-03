"""Hermetic execution context (§203).

Every host-sensitive access — filesystem roots, workspace paths, the clock —
goes through `ProjectContext`. Analyzers and checks never touch `os`,
`pathlib.Path.cwd()` or `datetime.now()` directly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

Clock = Callable[[], datetime]


def system_clock() -> Clock:
    """The one wall-clock source — injected at process boundaries only."""
    return lambda: datetime.now(UTC)


class ContextError(ValueError):
    """Raised when a path or clock request violates the hermetic boundary."""


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    workspace_paths: tuple[str, ...] = ()
    clock: Clock | None = None

    @classmethod
    def from_root(
        cls,
        root: str | Path,
        *,
        workspace_paths: tuple[str, ...] = (),
        clock: Clock | None = None,
    ) -> ProjectContext:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise ContextError(f"project root is not a directory: {root}")
        context = cls(
            root=resolved, workspace_paths=tuple(sorted(set(workspace_paths))), clock=clock
        )
        for workspace in context.workspace_paths:
            if not context.resolve(workspace).is_dir():
                raise ContextError(f"workspace path is not a directory: {workspace}")
        return context

    def resolve(self, relative: str) -> Path:
        """Resolve a project-relative POSIX path, refusing anything outside the root."""
        pure = PurePosixPath(relative.replace("\\", "/"))
        if pure.is_absolute() or (pure.parts and pure.parts[0].endswith(":")):
            raise ContextError(f"path must be relative to the project root: {relative}")
        candidate = (self.root / Path(*pure.parts)).resolve()
        if not candidate.is_relative_to(self.root):
            raise ContextError(f"path escapes the project root: {relative}")
        return candidate

    def relative(self, path: Path) -> str:
        """Render a host path as a stable project-relative POSIX string."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ContextError(f"path is outside the project root: {path}")
        return resolved.relative_to(self.root).as_posix() or "."

    def exists(self, relative: str) -> bool:
        return self.resolve(relative).exists()

    def read_text(self, relative: str) -> str:
        return self.resolve(relative).read_text(encoding="utf-8")

    def open_binary(self, relative: str) -> BinaryIO | None:
        """Open a project-relative file for streaming reads; None when absent."""
        path = self.resolve(relative)
        if not path.is_file():
            return None
        return path.open("rb")

    def iter_files(self, pattern: str = "**/*") -> Iterator[str]:
        """Yield project-relative file paths matching `pattern`, in sorted order."""
        matches = (
            self.relative(path)
            for path in self.root.glob(pattern)
            if path.is_file() and path.resolve().is_relative_to(self.root)
        )
        yield from sorted(matches)

    def now(self) -> datetime:
        """Return the injected clock's time; there is no implicit wall clock."""
        if self.clock is None:
            raise ContextError("no clock injected into ProjectContext")
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ContextError("injected clock must return timezone-aware datetimes")
        return value
