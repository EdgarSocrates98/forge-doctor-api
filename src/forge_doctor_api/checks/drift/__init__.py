"""DRIFT### suite (§14): OpenAPI contract vs implementation comparison."""

from forge_doctor_api.checks.drift.catalog import BY_ID, CATALOG, ContractAuthority, DriftCheckSpec
from forge_doctor_api.checks.drift.engine import (
    ApiErrorModel,
    DriftPair,
    DriftReport,
    contract_drift,
    normalize_path,
    path_vars,
)
from forge_doctor_api.checks.drift.error_contract import (
    RFC7807,
    ErrorConformance,
    ErrorContract,
    ErrorContractReport,
    ErrorVerdict,
    evaluate_error_contract,
)

__all__ = [
    "BY_ID",
    "CATALOG",
    "RFC7807",
    "ApiErrorModel",
    "ContractAuthority",
    "DriftCheckSpec",
    "DriftPair",
    "DriftReport",
    "ErrorConformance",
    "ErrorContract",
    "ErrorContractReport",
    "ErrorVerdict",
    "contract_drift",
    "evaluate_error_contract",
    "normalize_path",
    "path_vars",
]
