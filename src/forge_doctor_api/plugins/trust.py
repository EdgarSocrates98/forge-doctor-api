"""§132 plugin trust boundary.

Trust classes mirror the Forge philosophy: UNTRUSTED plugins may be
*listed* (for inventory, review, or operator action) but are never
imported or executed. `load_plugin` refuses them outright — the class is
binding, not advisory.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from enum import StrEnum
from types import ModuleType

from forge_doctor_api.core.models import Model, ModelError, UnknownFact


class TrustClass(StrEnum):
    """§132 plugin trust classes, strictest boundary last."""

    BUILTIN = "BUILTIN"             # shipped inside forge_doctor_api
    SIGNED = "SIGNED"               # verified signature evidence
    APPROVED_LOCAL = "APPROVED_LOCAL"  # operator-approved local path
    UNTRUSTED = "UNTRUSTED"         # listed, never loaded


@dataclass(frozen=True, kw_only=True)
class PluginDescriptor(Model):
    """Declared plugin — loading state separate from identity."""

    name: str
    module: str  # import path, e.g. "forge_doctor_api.analyzers.routes.fastapi"
    trust: TrustClass
    kind: str = ""  # sdk protocol name, e.g. "FrameworkAdapter"
    signature: str | None = None
    source: str | None = None  # where the descriptor was declared


@dataclass(frozen=True, kw_only=True)
class PluginRegistry(Model):
    """Known plugins — every one listed; only trusted ones loadable."""

    plugins: tuple[PluginDescriptor, ...] = ()

    @property
    def untrusted(self) -> tuple[PluginDescriptor, ...]:
        return tuple(p for p in self.plugins if p.trust is TrustClass.UNTRUSTED)

    @property
    def loadable(self) -> tuple[PluginDescriptor, ...]:
        return tuple(p for p in self.plugins if p.trust is not TrustClass.UNTRUSTED)


def load_plugin(descriptor: PluginDescriptor) -> ModuleType:
    """Import the plugin module iff its trust class permits it.

    UNTRUSTED raises — never imported, never executed (§132). BUILTIN is
    constrained to the `forge_doctor_api` package prefix so the class
    cannot be used as a loader for arbitrary code.
    """
    if descriptor.trust is TrustClass.UNTRUSTED:
        raise ModelError(
            f"plugin {descriptor.name!r} is UNTRUSTED: listed but never loaded"
        )
    module = descriptor.module
    if descriptor.trust is TrustClass.BUILTIN and not (
        module == "forge_doctor_api" or module.startswith("forge_doctor_api.")
    ):
        raise ModelError(
            f"BUILTIN plugin {descriptor.name!r} must resolve inside "
            f"forge_doctor_api, got {module!r}"
        )
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ModelError(
            f"plugin {descriptor.name!r} failed to import: {exc}"
        ) from exc


def describe_untrusted(registry: PluginRegistry) -> tuple[UnknownFact, ...]:
    """§132 inventory aid — unknowns recording what was *not* loaded."""
    return tuple(
        UnknownFact(
            subject=p.name,
            missing="trust classification sufficient for loading",
            resolution="obtain a signature or operator approval; "
            "UNTRUSTED plugins are never executed",
        )
        for p in registry.untrusted
    )
