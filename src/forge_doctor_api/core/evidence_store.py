"""Evidence inventory — content-addressed store (§14).

`EvidenceStore` is the frozen snapshot analyzers, handoff and the
context broker share: every registered artifact is addressable by its
sha256, identical content dedups into one entry with a reference list,
and the origin map records which artifact classes claimed each path.

Build through `EvidenceStoreBuilder` during discovery; the built store
is immutable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.discovery import ArtifactClass, ArtifactInventory
from forge_doctor_api.core.models import Model

_CHUNK = 1 << 20  # 1 MiB streaming reads


def _sha256_stream(fh: BinaryIO) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = fh.read(_CHUNK)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


@dataclass(frozen=True, kw_only=True)
class ContentEntry(Model):
    """One content hash and every path that carries it (dedup refs)."""

    sha256: str
    size: int
    paths: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class EvidenceStore(Model):
    """Immutable content-addressed artifact store (§14)."""

    entries: tuple[ContentEntry, ...] = ()
    # path -> sorted artifact classes (origin map; analyzer claims are
    # appended by the unified scan when a domain consumes the file).
    origins: tuple[tuple[str, tuple[ArtifactClass, ...]], ...] = ()
    # path -> sha256 index (tuple of pairs keeps the model serializable).
    index: tuple[tuple[str, str], ...] = ()

    def hash_of(self, path: str) -> str | None:
        for p, sha in self.index:
            if p == path:
                return sha
        return None

    def entry(self, sha256: str) -> ContentEntry | None:
        for e in self.entries:
            if e.sha256 == sha256:
                return e
        return None

    def paths_for(self, sha256: str) -> tuple[str, ...]:
        entry = self.entry(sha256)
        return entry.paths if entry is not None else ()

    def classes_of(self, path: str) -> tuple[ArtifactClass, ...]:
        for p, classes in self.origins:
            if p == path:
                return classes
        return ()


class EvidenceStoreBuilder:
    """Mutable accumulator — `build()` freezes into `EvidenceStore`."""

    def __init__(self) -> None:
        self._by_hash: dict[str, tuple[int, list[str]]] = {}
        self._by_path: dict[str, str] = {}
        self._origins: dict[str, tuple[ArtifactClass, ...]] = {}

    def register(
        self,
        path: str,
        sha256: str,
        size: int,
        classes: tuple[ArtifactClass, ...],
    ) -> None:
        if path in self._by_path:
            raise ValueError(f"duplicate artifact registration: {path}")
        self._by_path[path] = sha256
        if sha256 not in self._by_hash:
            self._by_hash[sha256] = (size, [])
        self._by_hash[sha256][1].append(path)
        self._origins[path] = classes

    def build(self) -> EvidenceStore:
        entries = tuple(
            ContentEntry(
                sha256=sha, size=size, paths=tuple(sorted(paths)),
            )
            for sha, (size, paths) in sorted(self._by_hash.items())
        )
        origins = tuple(
            (path, classes)
            for path, classes in sorted(self._origins.items())
        )
        index = tuple(sorted(self._by_path.items()))
        return EvidenceStore(entries=entries, origins=origins, index=index)


def build_evidence_store(
    context: ProjectContext,
    inventory: ArtifactInventory,
) -> EvidenceStore:
    """Hash every non-vendored artifact (one pass, chunked reads).

    Unreadable or vendored files are skipped — the inventory already
    records them with `unreadable`/`vendored` flags.
    """
    builder = EvidenceStoreBuilder()
    for artifact in inventory.artifacts:
        if artifact.vendored or artifact.unreadable:
            continue
        fh = context.open_binary(artifact.path)
        if fh is None:
            continue
        with fh:
            sha = _sha256_stream(fh)
        try:
            size = context.resolve(artifact.path).stat().st_size
        except OSError:
            size = 0
        builder.register(artifact.path, sha, size, artifact.classes)
    return builder.build()
