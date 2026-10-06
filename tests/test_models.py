from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from forge_doctor_api.core import models
from forge_doctor_api.core.models import (
    SLO,
    Baseline,
    Capability,
    CapabilityDependency,
    ChangeEvent,
    Confidence,
    DecisionContext,
    Entity,
    Evidence,
    EvidenceKind,
    Experiment,
    ExperimentVerdict,
    Finding,
    Model,
    ModelError,
    Regression,
    Relationship,
    Remediation,
    RemediationSafety,
    RuntimeEvidence,
    Severity,
    SourceLocation,
    UnknownFact,
    entity_id,
)

T0 = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

EVIDENCE = Evidence(
    kind=EvidenceKind.STATIC, source="openapi.yaml", summary="paths./payments", line=12
)
UNKNOWN = UnknownFact(
    subject="endpoint:http:GET:/payments/{id}",
    missing="gateway timeout config",
    resolution="provide gateway export",
)
LOCATION = SourceLocation(path="api/openapi.yaml", line=12, column=5)


def sample_models() -> list[Model]:
    return [
        EVIDENCE,
        UNKNOWN,
        Finding(
            id="OAS001",
            title="Missing operationId",
            description="GET /payments/{id} has no operationId",
            severity=Severity.MEDIUM,
            confidence=Confidence.HIGH,
            evidence_kind=EvidenceKind.STATIC,
            evidence=(EVIDENCE,),
            entity_ids=("operation:openapi:getPayment",),
            source_location=LOCATION,
            remediation="add a unique operationId",
            unknowns=(UNKNOWN,),
        ),
        Entity(
            id="service:python:payments",
            kind="service",
            name="payments",
            attributes={"zeta": "1", "alpha": "2"},
        ),
        Relationship(
            kind="CALLS",
            source_id="service:python:payments",
            target_id="service:python:ledger",
            confidence=Confidence.HIGH,
            evidence=(EVIDENCE,),
        ),
        Capability(
            id="capability:payments:capture",
            name="capture payment",
            confidence=Confidence.MEDIUM,
            entity_ids=("service:python:payments",),
        ),
        CapabilityDependency(
            capability_id="capability:payments:capture",
            depends_on_id="capability:ledger:post",
        ),
        RuntimeEvidence(
            entity_id="endpoint:http:GET:/payments/{id}",
            metric="latency_p95",
            value=120.5,
            unit="ms",
            source="metrics.json",
            observed_at=T0,
        ),
        ChangeEvent(
            id="change-1",
            kind="contract",
            description="removed field amount",
            entity_ids=("operation:openapi:getPayment",),
            occurred_at=T0,
        ),
        Baseline(
            entity_id="endpoint:http:GET:/payments/{id}",
            metric="latency_p95",
            value=100.0,
            unit="ms",
            sample_count=500,
            window="7d",
        ),
        Regression(
            entity_id="endpoint:http:GET:/payments/{id}",
            metric="latency_p95",
            baseline_value=100.0,
            observed_value=180.0,
            unit="ms",
            confidence=Confidence.LOW,
        ),
        SLO(
            id="slo-availability",
            entity_id="api:openapi:payments-v1",
            objective="availability",
            target=0.999,
            unit="ratio",
            window="30d",
        ),
        Remediation(
            id="fix-1",
            finding_id="OAS001",
            summary="add operationId",
            safety=RemediationSafety.SAFE,
        ),
        Experiment(
            id="exp-1",
            hypothesis="lower timeout reduces retries",
            change="timeout 2s -> 1s",
            entity_ids=("service:python:payments",),
            verdict=ExperimentVerdict.INCONCLUSIVE,
        ),
        DecisionContext(
            question="Can v1 be retired?",
            facts=("v2 exists",),
            constraints=("clients pinned to v1",),
            capability_ids=("capability:payments:capture",),
            tradeoffs=("migration cost",),
            unknowns=(UNKNOWN,),
        ),
        LOCATION,
    ]


REQUIRED_MODELS = {
    "Evidence",
    "Finding",
    "Confidence",
    "Severity",
    "Entity",
    "Relationship",
    "Capability",
    "CapabilityDependency",
    "RuntimeEvidence",
    "ChangeEvent",
    "Baseline",
    "Regression",
    "SLO",
    "Remediation",
    "Experiment",
    "UnknownFact",
    "DecisionContext",
}


def test_all_universal_concepts_defined() -> None:
    assert set(dir(models)) >= REQUIRED_MODELS


def test_samples_cover_every_model_class() -> None:
    classes = {type(m).__name__ for m in sample_models()}
    assert classes == (REQUIRED_MODELS - {"Confidence", "Severity"}) | {"SourceLocation"}


def test_evidence_kinds_match_spec() -> None:
    assert [k.value for k in EvidenceKind] == [
        "STATIC",
        "CONFIG",
        "OBSERVED_METADATA",
        "RUNTIME",
        "DERIVED",
    ]


def test_confidence_has_first_class_unknown() -> None:
    assert Confidence("UNKNOWN") is Confidence.UNKNOWN


@pytest.mark.parametrize("model", sample_models(), ids=lambda m: type(m).__name__)
def test_dict_round_trip(model: Model) -> None:
    assert type(model).from_dict(model.to_dict()) == model


@pytest.mark.parametrize("model", sample_models(), ids=lambda m: type(m).__name__)
def test_json_round_trip(model: Model) -> None:
    assert type(model).from_json(model.to_json()) == model


@pytest.mark.parametrize("model", sample_models(), ids=lambda m: type(m).__name__)
def test_serialization_is_byte_identical(model: Model) -> None:
    rebuilt = type(model).from_json(model.to_json())
    assert model.to_json().encode() == rebuilt.to_json().encode()
    assert model.to_json() == model.to_json()


@pytest.mark.parametrize("model", sample_models(), ids=lambda m: type(m).__name__)
def test_keys_sorted_at_every_level(model: Model) -> None:
    def check(node: object) -> None:
        if isinstance(node, dict):
            assert list(node) == sorted(node)
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(json.loads(model.to_json()))


def test_mapping_insertion_order_does_not_leak() -> None:
    a = Entity(id="service:python:x", kind="service", name="x", attributes={"b": "1", "a": "2"})
    b = Entity(id="service:python:x", kind="service", name="x", attributes={"a": "2", "b": "1"})
    assert a.to_json() == b.to_json()
    assert a.to_json() == (
        '{"attributes":{"a":"2","b":"1"},"id":"service:python:x","kind":"service","name":"x"}'
    )


def test_datetimes_normalized_to_utc() -> None:
    offset = timezone(timedelta(hours=-3))
    local = ChangeEvent(id="c", kind="k", description="d", occurred_at=T0.astimezone(offset))
    utc = ChangeEvent(id="c", kind="k", description="d", occurred_at=T0)
    assert local.to_json() == utc.to_json()
    assert '"occurred_at":"2026-01-02T03:04:05+00:00"' in utc.to_json()


def test_no_implicit_timestamp() -> None:
    event = ChangeEvent(id="c", kind="k", description="d")
    assert event.occurred_at is None
    assert '"occurred_at":null' in event.to_json()


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ModelError, match="timezone-aware"):
        ChangeEvent(id="c", kind="k", description="d", occurred_at=datetime(2026, 1, 1))  # noqa: DTZ001


def test_sets_rejected_in_serialization() -> None:
    finding = Finding(
        id="TST001",
        title="t",
        description="d",
        severity=Severity.LOW,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.DERIVED,
        entity_ids={"b", "a"},  # type: ignore[arg-type]
    )
    with pytest.raises(ModelError, match="sets are not allowed"):
        finding.to_json()


def test_models_are_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        EVIDENCE.source = "other"  # type: ignore[misc]


def test_entity_id_builder() -> None:
    assert entity_id("endpoint", "http", "GET:/payments/{id}") == "endpoint:http:GET:/payments/{id}"
    with pytest.raises(ModelError):
        entity_id("end:point", "http", "x")
    with pytest.raises(ModelError):
        entity_id("endpoint", "", "x")


@pytest.mark.parametrize(
    ("raw_id", "kind"),
    [
        ("payments", "service"),
        ("service:python", "service"),
        ("service::payments", "service"),
        ("api:python:payments", "service"),
    ],
)
def test_entity_rejects_non_canonical_ids(raw_id: str, kind: str) -> None:
    with pytest.raises(ModelError):
        Entity(id=raw_id, kind=kind, name="payments")


@pytest.mark.parametrize(
    "build",
    [
        lambda: Evidence(kind=EvidenceKind.STATIC, source="", summary="s"),
        lambda: Evidence(kind=EvidenceKind.STATIC, source="f", summary="s", line=0),
        lambda: Finding(
            id=" ",
            title="t",
            description="d",
            severity=Severity.LOW,
            confidence=Confidence.LOW,
            evidence_kind=EvidenceKind.STATIC,
        ),
        lambda: CapabilityDependency(capability_id="a", depends_on_id="a"),
        lambda: RuntimeEvidence(
            entity_id="e", metric="m", value=float("nan"), unit="ms", source="s"
        ),
        lambda: Baseline(
            entity_id="e", metric="m", value=1.0, unit="ms", sample_count=-1, window="1d"
        ),
        lambda: SLO(
            id="s", entity_id="e", objective="o", target=float("inf"), unit="u", window="w"
        ),
    ],
)
def test_invalid_construction_rejected(build: object) -> None:
    with pytest.raises(ModelError):
        build()  # type: ignore[operator]


def test_malformed_json_rejected() -> None:
    with pytest.raises(ModelError, match="malformed JSON"):
        Evidence.from_json("{not json")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "evidence",
        {"kind": "STATIC", "source": "f"},
        {"kind": "NOPE", "source": "f", "summary": "s"},
        {"kind": "STATIC", "source": 1, "summary": "s"},
        {"kind": "STATIC", "source": "f", "summary": "s", "line": "12"},
        {"kind": "STATIC", "source": "f", "summary": "s", "line": True},
        {"kind": "STATIC", "source": "f", "summary": "s", "extra": 1},
    ],
)
def test_malformed_payload_rejected(payload: object) -> None:
    with pytest.raises(ModelError):
        Evidence.from_dict(payload)


def test_malformed_nested_payload_rejected() -> None:
    data = sample_models()[2].to_dict()
    data["evidence"] = [{"kind": "STATIC"}]
    with pytest.raises(ModelError):
        Finding.from_dict(data)
    data["evidence"] = "not-a-list"
    with pytest.raises(ModelError, match="expected a list"):
        Finding.from_dict(data)


def test_malformed_datetime_rejected() -> None:
    data = {"id": "c", "kind": "k", "description": "d", "occurred_at": "yesterday"}
    with pytest.raises(ModelError, match="ISO 8601"):
        ChangeEvent.from_dict(data)


def test_integer_accepted_for_float_fields() -> None:
    data = sample_models()[9].to_dict()
    data["value"] = 100
    baseline = Baseline.from_dict(data)
    assert baseline.value == 100.0
    assert isinstance(baseline.value, float)
