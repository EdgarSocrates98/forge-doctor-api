"""Gateway + service-mesh declared-config models (§71-73, §196)."""

from forge_doctor_api.analyzers.gateway.model import (
    ConfigEntry,
    GatewayDialect,
    GatewayModel,
    GatewayRoute,
    MeshVendor,
    ServiceMeshModel,
)
from forge_doctor_api.analyzers.gateway.parser import (
    gateway_route_map,
    load_gateway_models,
)

__all__ = [
    "ConfigEntry",
    "GatewayDialect",
    "GatewayModel",
    "GatewayRoute",
    "MeshVendor",
    "ServiceMeshModel",
    "gateway_route_map",
    "load_gateway_models",
]
