"""Route discovery: framework adapters producing RouteModels (§12, §13, §192)."""

from forge_doctor_api.analyzers.routes.adapter import (
    AstFrameworkAdapter,
    FrameworkAdapter,
    available_adapters,
)
from forge_doctor_api.analyzers.routes.fastapi import FastApiAdapter
from forge_doctor_api.analyzers.routes.graph import scan_graph
from forge_doctor_api.analyzers.routes.model import (
    Attribution,
    ResponseSchemaSource,
    RouteModel,
    RouteParam,
    RouteScan,
    SurfaceItem,
    SurfaceResult,
)

__all__ = [
    "AstFrameworkAdapter",
    "Attribution",
    "FastApiAdapter",
    "FrameworkAdapter",
    "ResponseSchemaSource",
    "RouteModel",
    "RouteParam",
    "RouteScan",
    "SurfaceItem",
    "SurfaceResult",
    "available_adapters",
    "scan_graph",
]
