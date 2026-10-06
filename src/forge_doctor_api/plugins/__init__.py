"""§131-§132 plugin SDK + trust boundary.

Protocols are structural contracts; `load_plugin` is the only import
path and it refuses UNTRUSTED descriptors outright.
"""

from forge_doctor_api.plugins.manifest import (
    ManifestError,
    PluginManifest,
    parse_manifest,
)
from forge_doctor_api.plugins.registry import (
    PluginConflict,
    PluginRegistry,
    discover_registry,
)
from forge_doctor_api.plugins.sdk import (
    ContractAdapter,
    FrameworkAdapter,
    GatewayAdapter,
    RuntimeAdapter,
    SecurityRulePack,
)
from forge_doctor_api.plugins.trust import (
    PluginDescriptor,
    TrustClass,
    describe_untrusted,
    load_plugin,
)
from forge_doctor_api.plugins.trust import (
    PluginRegistry as LegacyPluginRegistry,
)

__all__ = [
    "ContractAdapter",
    "FrameworkAdapter",
    "GatewayAdapter",
    "LegacyPluginRegistry",
    "ManifestError",
    "PluginConflict",
    "PluginDescriptor",
    "PluginManifest",
    "PluginRegistry",
    "RuntimeAdapter",
    "SecurityRulePack",
    "TrustClass",
    "describe_untrusted",
    "discover_registry",
    "load_plugin",
    "parse_manifest",
]
