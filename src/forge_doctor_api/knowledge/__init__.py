"""§126-§130 knowledge supply chain: bundled packs + capability engine.

Capability symbols are lazy (`__getattr__`): the engine depends on the
analyzers, which themselves depend on `knowledge.loader` — eager imports
would cycle.
"""

from typing import TYPE_CHECKING, Any

from forge_doctor_api.knowledge.loader import (
    all_packs,
    domain_packs,
    knowledge_versions,
    load_pack,
    parse_pack,
)
from forge_doctor_api.knowledge.model import (
    MATURITY_STAGES,
    KnowledgePack,
    PackEntry,
    PackProvenance,
)

if TYPE_CHECKING:
    from forge_doctor_api.knowledge.capability import (
        DEPENDENCIES,
        Capability,
        CapabilityDependency,
        CapabilityGap,
        CapabilityReport,
        DependencyRule,
        DetectedCapability,
        detect_capabilities,
        pack_capabilities,
    )

_LAZY = {
    "DEPENDENCIES",
    "Capability",
    "CapabilityDependency",
    "CapabilityGap",
    "CapabilityReport",
    "DependencyRule",
    "DetectedCapability",
    "detect_capabilities",
    "pack_capabilities",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        from forge_doctor_api.knowledge import capability

        return getattr(capability, name)
    raise AttributeError(name)


__all__ = [
    "DEPENDENCIES",
    "MATURITY_STAGES",
    "Capability",
    "CapabilityDependency",
    "CapabilityGap",
    "CapabilityReport",
    "DependencyRule",
    "DetectedCapability",
    "KnowledgePack",
    "PackEntry",
    "PackProvenance",
    "all_packs",
    "detect_capabilities",
    "domain_packs",
    "knowledge_versions",
    "load_pack",
    "pack_capabilities",
    "parse_pack",
]
