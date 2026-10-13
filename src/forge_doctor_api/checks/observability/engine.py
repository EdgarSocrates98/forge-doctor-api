"""OBSAPI001-005 check engine (§85).

All findings are LOW/MEDIUM-confidence candidates over aggregated
observability evidence - runtime artifacts can't prove absence of
instrumentation that lives elsewhere.
"""

from __future__ import annotations

import re

from forge_doctor_api.analyzers.runtime.model import ApiObservabilityModel
from forge_doctor_api.checks.observability.catalog import BY_ID, ObsCheckSpec
from forge_doctor_api.core.models import (
    Evidence,
    Finding,
    SourceLocation,
    UnknownFact,
)

_CAMEL = re.compile(r"^[a-z]+[A-Z]")
_SNAKE = re.compile(r"_")
_KEBAB = re.compile(r"-")


def _finding(
    spec: ObsCheckSpec,
    description: str,
    unknowns: tuple[UnknownFact, ...] = (),
    path: str = "(runtime)",
) -> Finding:
    loc = SourceLocation(path=path)
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=spec.evidence_kind, source=path, summary=description
            ),
        ),
        source_location=loc,
        unknowns=unknowns,
    )


def run_observability_checks(model: ApiObservabilityModel) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    signals = model.signals

    # OBSAPI001: no correlation-id evidence anywhere
    if model.span_count + model.request_count > 0 and not (
        signals.get("correlation_ids") or signals.get("request_ids")
    ):
        findings.append(
            _finding(
                BY_ID["OBSAPI001"],
                f"{model.span_count} spans / {model.request_count} requests "
                f"with no correlation-id or request-id evidence",
                unknowns=(
                    UnknownFact(
                        subject="request correlation",
                        missing="correlation-id/request-id attributes or headers",
                        resolution="correlation may exist in artifact fields this "
                        "adapter does not map",
                    ),
                ),
            )
        )

    # OBSAPI002: spans present but no propagation evidence
    if model.span_count > 0 and not signals.get("trace_propagation"):
        findings.append(
            _finding(
                BY_ID["OBSAPI002"],
                "no trace-propagation evidence (no parent links, traceparent "
                "or b3 headers) across spans",
                unknowns=(
                    UnknownFact(
                        subject="trace propagation",
                        missing="propagation header/parent evidence",
                        resolution="propagation may occur upstream of these "
                        "artifacts",
                    ),
                ),
            )
        )
    elif model.orphan_spans:
        findings.append(
            _finding(
                BY_ID["OBSAPI002"],
                f"{model.orphan_spans} span(s) reference parents absent from "
                f"the export - partial propagation visibility",
                unknowns=(
                    UnknownFact(
                        subject="orphan spans",
                        missing="the parent spans the export does not contain",
                        resolution="re-export a complete trace window",
                    ),
                ),
            )
        )

    # OBSAPI003: inconsistent operation naming conventions
    if len(model.operation_names) > 2:
        styles = {
            "camel": [n for n in model.operation_names if _CAMEL.search(n)],
            "snake": [n for n in model.operation_names if _SNAKE.search(n)],
            "kebab": [n for n in model.operation_names if _KEBAB.search(n)],
        }
        mixed = [k for k, v in styles.items() if v]
        if len(mixed) > 1:
            detail = "; ".join(f"{k}: {v[:3]}" for k, v in styles.items() if v)
            findings.append(
                _finding(
                    BY_ID["OBSAPI003"],
                    f"operation names mix conventions ({detail})",
                )
            )

    # OBSAPI004: error spans without structured context
    if model.error_spans_without_context:
        findings.append(
            _finding(
                BY_ID["OBSAPI004"],
                f"{model.error_spans_without_context} error-status span(s) "
                f"lack error/exception attributes",
                unknowns=(
                    UnknownFact(
                        subject="error context",
                        missing="error.type/error.message/exception attributes",
                        resolution="emit structured error attributes on failure "
                        "spans",
                    ),
                ),
            )
        )

    # OBSAPI005: latency metrics missing
    if model.span_count > 0 and model.spans_without_duration:
        findings.append(
            _finding(
                BY_ID["OBSAPI005"],
                f"{model.spans_without_duration} of {model.span_count} span(s) "
                f"have no duration - latency metrics absent",
                unknowns=(
                    UnknownFact(
                        subject="latency",
                        missing="start/end timestamps on spans",
                        resolution="latency may live in a metrics artifact not "
                        "provided",
                    ),
                ),
            )
        )
    return tuple(findings)
