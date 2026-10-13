"""§133-§138, §215 handoff & integration surface."""

from forge_doctor_api.handoff.bundle import assemble_bundle
from forge_doctor_api.handoff.decision import (
    answer_become_async,
    answer_enable_retry_safely,
    answer_move_to_grpc,
    answer_retire_version,
)
from forge_doctor_api.handoff.mcp import DoctorApi
from forge_doctor_api.handoff.model import (
    ApiHandoffBundle,
    ExternalReference,
    ForgerRequest,
    ForgerRoute,
)
from forge_doctor_api.handoff.routing import route_request

__all__ = [
    "ApiHandoffBundle",
    "DoctorApi",
    "ExternalReference",
    "ForgerRequest",
    "ForgerRoute",
    "answer_become_async",
    "answer_enable_retry_safely",
    "answer_move_to_grpc",
    "answer_retire_version",
    "assemble_bundle",
    "route_request",
]
