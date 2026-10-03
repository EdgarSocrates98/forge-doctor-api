"""§147 org standard-error-contract evaluation.

`ApiErrorModel` compares contract vs impl error surfaces; this module
extends that with an org-declared contract (e.g. RFC 7807 problem+json)
evaluated per operation over the OpenAPI model's declared error
responses. Operations without declared error responses are UNKNOWN —
absence of a contract surface is not conformance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
    OperationSource,
)
from forge_doctor_api.core.models import Evidence, EvidenceKind, Model

_ERROR_STATUS = re.compile(r"^(4\d\d|5\d\d|default)$")
_PROPS = re.compile(r"props\((?P<props>[^)]*)\)")


@dataclass(frozen=True, kw_only=True)
class ErrorContract(Model):
    """An org-declared standard error contract (§147)."""

    name: str
    required_content_types: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    require_error_responses: bool = True


class ErrorConformance(StrEnum):
    CONFORMS = "CONFORMS"
    VIOLATION = "VIOLATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class ErrorVerdict(Model):
    subject: str
    status: ErrorConformance
    detail: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ErrorContractReport(Model):
    contract: str
    verdicts: tuple[ErrorVerdict, ...] = ()


def _props_tokens(shapes: tuple[str, ...]) -> frozenset[str]:
    out: set[str] = set()
    for shape in shapes:
        m = _PROPS.search(shape)
        if m:
            out.update(
                p.strip() for p in m["props"].split(",") if p.strip())
    return frozenset(out)


def _eval_op(
    op: OpenApiOperation,
    model: OpenApiProjectModel,
    contract: ErrorContract,
) -> ErrorVerdict:
    responses = [r for r in model.responses
                 if r.pointer in op.response_pointers]
    errors = [r for r in responses
              if r.status is not None and _ERROR_STATUS.match(r.status)]
    loc = op.location
    ev = (
        Evidence(kind=EvidenceKind.STATIC, source=loc.path,
                 summary=f"error surface of {op.identity}", line=loc.line),
    )
    if not errors:
        status = (ErrorConformance.UNKNOWN
                  if contract.require_error_responses
                  else ErrorConformance.CONFORMS)
        return ErrorVerdict(
            subject=op.identity, status=status,
            detail="no declared error responses"
            if contract.require_error_responses else "no error surface to check",
            evidence=ev)

    missing_ct = sorted(set(contract.required_content_types) - {
        ct for r in errors for ct in r.content_types})
    missing_fields = sorted(set(contract.required_fields) - {
        p for r in errors for p in _props_tokens(r.schema_shapes)})
    if missing_ct or missing_fields:
        bits = []
        if missing_ct:
            bits.append(f"missing content types {missing_ct}")
        if missing_fields:
            bits.append(f"missing fields {missing_fields}")
        return ErrorVerdict(
            subject=op.identity, status=ErrorConformance.VIOLATION,
            detail="; ".join(bits), evidence=ev)
    return ErrorVerdict(
        subject=op.identity, status=ErrorConformance.CONFORMS,
        detail="declared error surface conforms", evidence=ev)


def evaluate_error_contract(
    model: OpenApiProjectModel,
    contract: ErrorContract,
) -> ErrorContractReport:
    """Evaluate every operation's error surface against `contract`."""
    return ErrorContractReport(
        contract=contract.name,
        verdicts=tuple(
            _eval_op(op, model, contract)
            for op in model.operations
            if op.source is OperationSource.PATH),
    )


RFC7807 = ErrorContract(
    name="rfc7807-problem-json",
    required_content_types=("application/problem+json",),
    required_fields=("type", "title", "status"),
)
