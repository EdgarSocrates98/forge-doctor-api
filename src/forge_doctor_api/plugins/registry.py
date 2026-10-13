"""Plugin registry — discovery, metadata, trust-gated activation.

Two discovery channels, both manifest-only:

- installed packages exposing the `forge_doctor_api.plugins`
  entry-point group (their metadata is read; nothing is imported);
- a local `plugins/` directory scanned for manifest files.

`activate()` is the single trust gate: UNTRUSTED manifests are listed
and inspectable but *never imported* — the class is binding, matching
the `load_plugin` invariant in `trust.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType

from forge_doctor_api.core.models import Model, ModelError
from forge_doctor_api.plugins.manifest import (
    ManifestError,
    PluginManifest,
    discover_manifests,
    manifest_compatible,
)
from forge_doctor_api.plugins.trust import TrustClass, load_plugin
from forge_doctor_api.sdk import SDK_VERSION

ENTRY_POINT_GROUP = "forge_doctor_api.plugins"


@dataclass(frozen=True, kw_only=True)
class PluginConflict(Model):
    """A surfaced collision between registered plugins."""

    kind: str          # "duplicate-id" | "capability"
    detail: str
    plugins: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class PluginRegistry(Model):
    """Discovered plugins: manifests + rejection reasons, sorted."""

    manifests: tuple[PluginManifest, ...] = ()
    rejections: tuple[ManifestError, ...] = ()

    def list(self) -> tuple[PluginManifest, ...]:
        return self.manifests

    def get(self, plugin_id: str) -> PluginManifest | None:
        return next(
            (m for m in self.manifests if m.plugin_id == plugin_id),
            None)

    def compatible(self, manifest: PluginManifest) -> bool:
        return manifest_compatible(manifest, SDK_VERSION)

    def conflicts(self) -> tuple[PluginConflict, ...]:
        out: list[PluginConflict] = []
        ids: dict[str, list[str]] = {}
        caps: dict[str, list[str]] = {}
        for m in self.manifests:
            ids.setdefault(m.plugin_id, []).append(m.source)
            for cap in m.capabilities:
                caps.setdefault(cap, []).append(m.plugin_id)
        out += [
            PluginConflict(
                kind="duplicate-id",
                detail=f"id {pid} declared {len(srcs)} times",
                plugins=tuple(sorted(srcs)))
            for pid, srcs in ids.items() if len(srcs) > 1]
        out += [
            PluginConflict(
                kind="capability",
                detail=f"capability {cap} claimed by {plugins}",
                plugins=tuple(sorted(plugins)))
            for cap, plugins in caps.items() if len(plugins) > 1]
        return tuple(sorted(out, key=lambda c: (c.kind, c.detail)))

    def activate(self, plugin_id: str) -> ModuleType:
        """Import the plugin module — ONLY through the trust gate.

        UNTRUSTED (or absent) raises ModelError; the plugin module is
        never imported on any failure path.
        """
        manifest = self.get(plugin_id)
        if manifest is None:
            raise ModelError(f"unknown plugin {plugin_id!r}")
        if manifest.trust is TrustClass.UNTRUSTED:
            raise ModelError(
                f"plugin {plugin_id!r} is UNTRUSTED: listed but never "
                "loaded")
        if not self.compatible(manifest):
            raise ModelError(
                f"plugin {plugin_id!r} requires doctor_api "
                f"{manifest.doctor_api!r}, sdk is {SDK_VERSION}")
        from forge_doctor_api.plugins.trust import PluginDescriptor
        return load_plugin(PluginDescriptor(
            name=manifest.plugin_id, module=manifest.module,
            trust=manifest.trust, kind="manifest",
            signature=manifest.signature, source=manifest.source))


def discover_registry(plugins_dir: Path | None = None) -> PluginRegistry:
    """Manifests from entry-points + `plugins_dir` scan, sorted."""
    manifests: list[PluginManifest] = []
    rejections: list[ManifestError] = []
    for ep in sorted(
            entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name):
        # Entry points carry metadata only; the manifest table lives in
        # the dist's own metadata — never an import. A dist without a
        # readable manifest is a rejection, not a guess.
        rejections.append(ManifestError(
            path=f"entry-point:{ep.name}",
            reason="entry-point plugins must also ship a readable "
            "manifest file; nothing was imported"))
    if plugins_dir is not None and plugins_dir.is_dir():
        for manifest, errors in discover_manifests(plugins_dir):
            if manifest is not None:
                manifests.append(manifest)
            rejections.extend(errors)
    return PluginRegistry(
        manifests=tuple(sorted(
            manifests, key=lambda m: (m.plugin_id, m.source))),
        rejections=tuple(sorted(
            rejections, key=lambda r: (r.path, r.reason))))
