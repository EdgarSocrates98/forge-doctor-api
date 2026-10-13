"""Plugin manifest — declarative identity, parsed as DATA only.

A manifest is `forge-doctor-plugin.toml` or `[tool.forge-doctor.plugin]`
inside `pyproject.toml`. Parsing never imports the plugin module — the
manifest is how the registry learns about a plugin *without* trusting
it.

Trust is re-validated, never taken on the plugin's word:

- `BUILTIN` requires the module to live inside `forge_doctor_api`;
- `SIGNED` requires a `signature` field (verification record — the
  crypto itself is roadmap);
- `APPROVED_LOCAL` requires an explicit local source path;
- anything else — missing, misspelled, self-elevated without evidence —
  degrades to `UNTRUSTED` (listed, never imported).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge_doctor_api.core.models import Model
from forge_doctor_api.plugins.trust import TrustClass

MANIFEST_NAMES = ("forge-doctor-plugin.toml", "pyproject.toml")
_TABLE = ("tool", "forge-doctor", "plugin")

_SEMVER = re.compile(r"^\d+\.\d+(\.\d+)?([-.][0-9A-Za-z.-]+)?$")
_LT = chr(60)  # kept out of source text tooling edge cases
_OPS = (">=", _LT + "=", "==", "!=", ">", _LT, "=")


@dataclass(frozen=True, kw_only=True)
class ManifestError(Model):
    """One reason a manifest was rejected (never partial trust)."""

    path: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class PluginManifest(Model):
    """Validated plugin declaration (spec 053)."""

    plugin_id: str
    version: str
    module: str
    trust: TrustClass
    doctor_api: str = ""          # version specifier set, e.g. ">=0.1,<0.2"
    capabilities: tuple[str, ...] = ()
    signature: str | None = None
    source: str = ""              # manifest file it was declared in


def _spec_ok(spec: str, version: str) -> bool:
    """Tiny specifier-set check: comma-separated `OP ver` parts."""
    cur = tuple(int(p) for p in version.split(".")[:3])
    cur += (0,) * (3 - len(cur))
    for part in spec.split(","):
        part = part.strip()
        op, _, ver = next(
            ((o, "", part[len(o):].strip()) for o in _OPS
             if part.startswith(o)), ("", "", ""))
        if not op or not _SEMVER.match(ver):
            return False
        tgt = tuple(int(p) for p in re.split(r"[.-]", ver)[:3])
        tgt += (0,) * (3 - len(tgt))
        if op == ">=" and not cur >= tgt:
            return False
        if op == _LT + "=" and not cur <= tgt:
            return False
        if op == ">" and not cur > tgt:
            return False
        if op == _LT and not cur < tgt:
            return False
        if op in ("==", "=") and cur != tgt:
            return False
        if op == "!=" and cur == tgt:
            return False
    return True


def _revalidated(data: dict[str, Any], errors: list[str]) -> TrustClass:
    """Declared trust, re-checked against hard requirements."""
    raw = str(data.get("trust_class", "UNTRUSTED")).upper()
    module = str(data.get("module", ""))
    if raw == "BUILTIN":
        if not module.startswith("forge_doctor_api"):
            errors.append(
                "BUILTIN requires module under forge_doctor_api")
            return TrustClass.UNTRUSTED
        return TrustClass.BUILTIN
    if raw == "SIGNED":
        if not data.get("signature"):
            errors.append("SIGNED requires a signature field")
            return TrustClass.UNTRUSTED
        return TrustClass.SIGNED
    if raw == "APPROVED_LOCAL":
        if not data.get("source"):
            errors.append("APPROVED_LOCAL requires a source path")
            return TrustClass.UNTRUSTED
        return TrustClass.APPROVED_LOCAL
    if raw != "UNTRUSTED":
        errors.append(f"unknown trust_class {raw!r}")
    return TrustClass.UNTRUSTED


def parse_manifest(
    path: str | Path, *, source: str | None = None,
) -> tuple[PluginManifest | None, tuple[ManifestError, ...]]:
    """Strict TOML parse: rejected -> (None, errors), never partial."""
    p = Path(path)
    errors: list[str] = []
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, (ManifestError(
            path=str(p), reason=f"unparseable TOML: {exc}"),)
    table: Any = data
    for key in _TABLE:
        table = table.get(key) if isinstance(table, dict) else None
        if table is None:
            return None, (ManifestError(
                path=str(p), reason="no [tool.forge-doctor.plugin] table"),)
    known = {"id", "version", "module", "doctor_api", "capabilities",
             "trust_class", "signature", "source"}
    unknown = sorted(set(table) - known)
    if unknown:
        errors.append(f"unknown manifest keys: {unknown}")
    pid = str(table.get("id", "")).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-_.]*", pid):
        errors.append("id must be [a-z0-9-_.]+")
    version = str(table.get("version", "")).strip()
    if not _SEMVER.match(version):
        errors.append(f"version {version!r} is not semver")
    module = str(table.get("module", "")).strip()
    if not re.fullmatch(r"[A-Za-z_][\w.]*", module):
        errors.append("module must be a dotted import path")
    caps = table.get("capabilities", [])
    if not isinstance(caps, list) or not all(
            isinstance(c, str) for c in caps):
        errors.append("capabilities must be a string list")
        caps = []
    doctor_api = str(table.get("doctor_api", "")).strip()
    trust = _revalidated(table, errors)
    if errors:
        return None, tuple(
            ManifestError(path=str(p), reason=e) for e in errors)
    return PluginManifest(
        plugin_id=pid, version=version, module=module, trust=trust,
        doctor_api=doctor_api,
        capabilities=tuple(sorted(caps)),
        signature=table.get("signature"),
        source=source or str(p)), ()


def manifest_compatible(manifest: PluginManifest, sdk_version: str) -> bool:
    """doctor_api specifier check against the running SDK version."""
    if not manifest.doctor_api:
        return True  # no constraint declared
    return _spec_ok(manifest.doctor_api, sdk_version)


def discover_manifests(root: Path) -> tuple[tuple[PluginManifest | None,
        tuple[ManifestError, ...]], ...]:
    """Scan `root` one level deep for manifest files."""
    out: list[tuple[PluginManifest | None, tuple[ManifestError, ...]]] = []
    for name in MANIFEST_NAMES:
        direct = root / name
        if direct.is_file():
            out.append(parse_manifest(direct))
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        for name in MANIFEST_NAMES:
            f = child / name
            if f.is_file():
                out.append(parse_manifest(f))
    return tuple(out)
