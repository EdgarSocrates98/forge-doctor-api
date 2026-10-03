"""Route discovery: framework adapters producing RouteModels (§12, §13, §192)."""

from forge_doctor_api.analyzers.routes.adapter import FrameworkAdapter
from forge_doctor_api.analyzers.routes.fastapi import FastApiAdapter
from forge_doctor_api.analyzers.routes.graph import scan_graph
from forge_doctor_api.analyzers.routes.model import (
    Attribution,
    ResponseSchemaSource,
    RouteModel,
    RouteScan,
)

__all__ = [
    "Attribution",
    "FastApiAdapter",
    "FrameworkAdapter",
    "ResponseSchemaSource",
    "RouteModel",
    "RouteScan",
    "scan_graph",
]
