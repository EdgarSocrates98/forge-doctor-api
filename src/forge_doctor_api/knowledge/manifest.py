"""Spec 064 — external knowledge-pack manifests + lifecycle.

External packs (project dir, explicit `--knowledge` dir) declare a
`forge-doctor-knowledge.toml` manifest: id, version, `doctor_compat`
range, `provides`, `requires`. Strict parse — malformed manifests are
listed with errors, never partially loaded.

Precedence (documented): explicit dir > project dir > builtin. Same
manifest id twice = a conflict; the first entry in precedence wins
deterministically and the loser is listed with a warning.

Compat: a tiny stdlib semver-range parser (`>=`, `<=`, `>`, `<`, `==`,
`!=`, comma-separated). Incompatible packs are skipped + UnknownFact —
never silently used.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from forge_doctor_api import __version__
from forge_doctor_api.core.models import Model, UnknownFact

MANIFEST_NAME = "forge-doctor-knowledge.toml"


class PackStatus(StrEnum):
    ACTIVE = "active"
    INCOMPATIBLE = "skipped-incompatible"
    CONFLICT = "conflict-shadowed"
    REJECTED = "rejected"


@dataclass(frozen=True, kw_only=True)
class PackManifest(Model):
    """Strict manifest for one external knowledge pack."""

    id: str
    version: str
    doctor_compat: str = ""          # e.g. ">=0.1,<0.3"
    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PackListing(Model):
    """One discovered manifest + its lifecycle status."""

    manifest: PackManifest | None
    source: str
    status: PackStatus
    details: str = ""


# -- strict parse -------------------------------------------------------------


def _strs(v: Any) -> tuple[str, ...] | None:
    if v is None:
        return ()
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        return None
    return tuple(sorted(v))


def load_manifest(path: Path) -> tuple[PackManifest | None, tuple[str, ...]]:
    """Parse `path`/MANIFEST_NAME or a direct toml file. All errors listed."""
    file = path / MANIFEST_NAME if path.is_dir() else path
    if not file.is_file():
        return None, (f"{file}: manifest not found",)
    try:
        doc = tomllib.loads(file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        return None, (f"{file}: {e}",)
    errors: list[str] = []
    raw = doc.get("knowledge", doc)
    if not isinstance(raw, dict):
        return None, ("manifest root must be a table",)
    pid = raw.get("id")
    if not isinstance(pid, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9\-_.]*", pid or ""):
        errors.append(f"id must be a slug string, got {pid!r}")
    version = raw.get("version")
    if not isinstance(version, str) or _semver(version) is None:
        errors.append(f"version must be semver, got {version!r}")
    compat = raw.get("doctor_compat", "")
    if not isinstance(compat, str) or (compat and _parse_range(compat) is None):
        errors.append(f"doctor_compat must be a semver range, "
                      f"got {compat!r}")
    provides = _strs(raw.get("provides"))
    if provides is None:
        errors.append("provides must be a list of strings")
    requires = _strs(raw.get("requires"))
    if requires is None:
        errors.append("requires must be a list of strings")
    if errors:
        return None, tuple(errors)
    return PackManifest(
        id=pid, version=version, doctor_compat=compat,  # type: ignore[arg-type]
        provides=provides or (), requires=requires or ()), ()


# -- semver range (stdlib) ----------------------------------------------------


def _semver(v: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", v.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))


_RANGE_OP = re.compile(r"^(>=|<=|==|!=|>|<)\s*([0-9][0-9.]*)$")


def _parse_range(spec: str) -> tuple[tuple[str, tuple[int, int, int]], ...] | None:
    out: list[tuple[str, tuple[int, int, int]]] = []
    for part in spec.split(","):
        m = _RANGE_OP.match(part.strip())
        v = m and _semver(m.group(2))
        if not m or v is None:
            return None
        out.append((m.group(1), v))
    return tuple(out)


def compatible(manifest: PackManifest,
               engine: str = __version__) -> tuple[bool, str]:
    """engine version vs manifest.doctor_compat. Empty range = any."""
    if not manifest.doctor_compat:
        return True, ""
    ev = _semver(engine)
    rng = _parse_range(manifest.doctor_compat)
    if ev is None or rng is None:
        return False, f"unparseable range {manifest.doctor_compat!r}"
    for op, bound in rng:
        ok = {
            ">=": ev >= bound, "<=": ev <= bound, ">": ev > bound,
            "<": ev < bound, "==": ev == bound, "!=": ev != bound,
        }[op]
        if not ok:
            return False, f"engine {engine} fails {op}{'.'.join(map(str, bound))}"
    return True, ""


# -- precedence + listing -----------------------------------------------------

BUILTIN_PACK_DIR = Path(__file__).resolve().parent
BUILTIN_ID = "builtin"
PROJECT_PACK_DIR = ".forge-doctor/knowledge"


def _builtin_listing(engine: str) -> PackListing:
    """Builtin packs are pinned to the engine version (spec 064)."""
    return PackListing(
        manifest=PackManifest(
            id=BUILTIN_ID, version=engine,
            doctor_compat=f"=={engine}",
            provides=("openapi", "asyncapi", "graphql", "grpc",
                      "http", "jsonschema", "security", "frameworks",
                      "gateways")),
        source=str(BUILTIN_PACK_DIR),
        status=PackStatus.ACTIVE,
        details="pinned to engine version")


def list_packs(
    dirs: tuple[Path, ...],
    *,
    engine: str = __version__,
    include_builtin: bool = True,
) -> tuple[tuple[PackListing, ...], tuple[UnknownFact, ...]]:
    """Discover manifests under `dirs` (highest precedence first).

    `dirs` should already be ordered explicit > project. The builtin
    pack is appended last — always listed, shadowable by id.
    """
    listings: list[PackListing] = []
    unknowns: list[UnknownFact] = []
    seen: dict[str, PackListing] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        manifest, errors = load_manifest(d)
        if manifest is None:
            for e in errors:
                listings.append(PackListing(
                    manifest=None, source=str(d),
                    status=PackStatus.REJECTED, details=e))
                unknowns.append(UnknownFact(
                    subject=str(d), missing="valid knowledge manifest",
                    resolution=e))
            continue
        if manifest.id in seen:
            winner = seen[manifest.id]
            listings.append(PackListing(
                manifest=manifest, source=str(d),
                status=PackStatus.CONFLICT,
                details=f"shadowed by {winner.source} "
                        "(first in precedence wins)"))
            continue
        ok, reason = compatible(manifest, engine)
        status = PackStatus.ACTIVE if ok else PackStatus.INCOMPATIBLE
        if not ok:
            unknowns.append(UnknownFact(
                subject=manifest.id,
                missing="compatible doctor engine",
                resolution=reason))
        entry = PackListing(
            manifest=manifest, source=str(d), status=status,
            details=reason)
        listings.append(entry)
        seen[manifest.id] = entry
    if include_builtin:
        if BUILTIN_ID in seen:
            listings.append(PackListing(
                manifest=_builtin_listing(engine).manifest,
                source=str(BUILTIN_PACK_DIR),
                status=PackStatus.CONFLICT,
                details=f"shadowed by {seen[BUILTIN_ID].source} "
                        "(first in precedence wins)"))
        else:
            listings.append(_builtin_listing(engine))
    return tuple(listings), tuple(unknowns)
