"""API versioning + lifecycle model (§18, §19, §7.4)."""

from forge_doctor_api.analyzers.version.detect import detect_version_model
from forge_doctor_api.analyzers.version.model import (
    ApiVersion,
    ApiVersionModel,
    DeprecationModel,
    LifecycleState,
    VersionMechanism,
)

__all__ = [
    "ApiVersion",
    "ApiVersionModel",
    "DeprecationModel",
    "LifecycleState",
    "VersionMechanism",
    "detect_version_model",
]
