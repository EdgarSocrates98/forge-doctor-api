"""§131-§132 plugin SDK + trust boundary.

Protocols are structural contracts; `load_plugin` is the only import
path and it refuses UNTRUSTED descriptors outright.
"""

from forge_doctor_api.plugins.sdk import (
    ContractAdapter,
    FrameworkAdapter,
    GatewayAdapter,
    RuntimeAdapter,
    SecurityRulePack,
)
from forge_doctor_api.plugins.trust import (
    PluginDescriptor,
    PluginRegistry,
    TrustClass,
    describe_untrusted,
    load_plugin,
)

__all__ = [
    "ContractAdapter",
    "FrameworkAdapter",
    "GatewayAdapter",
    "PluginDescriptor",
    "PluginRegistry",
    "RuntimeAdapter",
    "SecurityRulePack",
    "TrustClass",
    "describe_untrusted",
    "load_plugin",
]
