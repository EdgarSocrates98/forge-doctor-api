"""§77-§83 migration intelligence - analysis only, never generation."""

from forge_doctor_api.migrate.engine import (
    assess_contract_version,
    assess_gateway_to_gateway,
    assess_rest_to_graphql,
    assess_rest_to_grpc,
    assess_sync_to_async,
    assess_version_upgrade,
    client_generation_impact,
    decide,
)
from forge_doctor_api.migrate.model import (
    ApiMigrationIntelligence,
    DecisionBrief,
    DecisionQuestion,
    DimensionResult,
    MigrationAssessment,
    MigrationClass,
    MigrationKind,
    SdkImpact,
)

__all__ = [
    "ApiMigrationIntelligence",
    "DecisionBrief",
    "DecisionQuestion",
    "DimensionResult",
    "MigrationAssessment",
    "MigrationClass",
    "MigrationKind",
    "SdkImpact",
    "assess_contract_version",
    "assess_gateway_to_gateway",
    "assess_rest_to_graphql",
    "assess_rest_to_grpc",
    "assess_sync_to_async",
    "assess_version_upgrade",
    "client_generation_impact",
    "decide",
]
