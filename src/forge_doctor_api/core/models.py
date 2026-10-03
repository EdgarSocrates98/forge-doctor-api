"""Core universal models (§5).

All models are frozen dataclasses with deterministic serialization:
keys are emitted in sorted order, mappings are sorted, datetimes are
normalized to UTC, and unordered collections (sets) are rejected so that
iteration order can never leak into output. No model reads the clock;
timestamps must be injected by the caller.
"""

from __future__ import annotations

import json
import math
import types
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any, Self, Union, get_args, get_origin, get_type_hints


class ModelError(ValueError):
    """Raised when a model is constructed or decoded from invalid data."""


class EvidenceKind(StrEnum):
    STATIC = "STATIC"
    CONFIG = "CONFIG"
    OBSERVED_METADATA = "OBSERVED_METADATA"
    RUNTIME = "RUNTIME"
    DERIVED = "DERIVED"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class RemediationSafety(StrEnum):
    SAFE = "SAFE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MANUAL_ONLY = "MANUAL_ONLY"


class ExperimentVerdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CONSTRAINT_VIOLATED = "CONSTRAINT_VIOLATED"


def _encode(value: Any) -> Any:
    if isinstance(value, Model):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, set | frozenset):
        raise ModelError("sets are not allowed in models: iteration order is not deterministic")
    if isinstance(value, tuple | list):
        return [_encode(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _encode(value[key]) for key in sorted(value)}
    return value


def _decode(tp: Any, value: Any, name: str) -> Any:
    origin = get_origin(tp)
    if origin is Union or origin is types.UnionType:
        args = get_args(tp)
        if value is None and type(None) in args:
            return None
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) != 1:
            raise ModelError(f"{name}: unsupported union type {tp!r}")
        return _decode(non_none[0], value, name)
    if origin is tuple:
        item_tp = get_args(tp)[0]
        if not isinstance(value, list | tuple):
            raise ModelError(f"{name}: expected a list, got {type(value).__name__}")
        return tuple(_decode(item_tp, item, f"{name}[{i}]") for i, item in enumerate(value))
    if origin is dict:
        key_tp, value_tp = get_args(tp)
        if not isinstance(value, Mapping):
            raise ModelError(f"{name}: expected an object, got {type(value).__name__}")
        return {
            _decode(key_tp, key, name): _decode(value_tp, item, f"{name}.{key}")
            for key, item in value.items()
        }
    if isinstance(tp, type) and issubclass(tp, Enum):
        try:
            return tp(value)
        except ValueError as exc:
            raise ModelError(f"{name}: invalid {tp.__name__} value {value!r}") from exc
    if isinstance(tp, type) and issubclass(tp, Model):
        return tp.from_dict(value)
    if tp is datetime:
        if not isinstance(value, str):
            raise ModelError(f"{name}: expected an ISO 8601 string")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ModelError(f"{name}: invalid ISO 8601 datetime {value!r}") from exc
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ModelError(f"{name}: expected a number")
        return float(value)
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ModelError(f"{name}: expected an integer")
        return value
    if tp is str:
        if not isinstance(value, str):
            raise ModelError(f"{name}: expected a string")
        return value
    raise ModelError(f"{name}: unsupported field type {tp!r}")


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{name} must be a non-empty string")


def _require_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ModelError(f"{name} must be a finite number")


def _require_aware(name: str, value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ModelError(f"{name} must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class Model:
    """Base for all core models: deterministic dict/JSON round-trip."""

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _encode(getattr(self, f.name)) for f in sorted(fields(self), key=_name)}

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        if not isinstance(data, Mapping):
            raise ModelError(f"{cls.__name__}: expected an object, got {type(data).__name__}")
        hints = get_type_hints(cls)
        known = {f.name for f in fields(cls)}
        unknown = sorted(str(key) for key in data if key not in known)
        if unknown:
            raise ModelError(f"{cls.__name__}: unknown fields {unknown}")
        kwargs = {
            name: _decode(hints[name], data[name], f"{cls.__name__}.{name}")
            for name in sorted(known)
            if name in data
        }
        try:
            return cls(**kwargs)
        except TypeError as exc:
            raise ModelError(f"{cls.__name__}: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> Self:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ModelError(f"{cls.__name__}: malformed JSON: {exc.msg}") from exc
        return cls.from_dict(data)


def _name(f: Any) -> str:
    return str(f.name)


def entity_id(kind: str, domain: str, identifier: str) -> str:
    """Build a canonical entity id `{kind}:{domain}:{identifier}` (§9)."""
    for part_name, part in (("kind", kind), ("domain", domain)):
        _require_text(part_name, part)
        if ":" in part:
            raise ModelError(f"{part_name} must not contain ':'")
    _require_text("identifier", identifier)
    return f"{kind}:{domain}:{identifier}"


@dataclass(frozen=True, kw_only=True)
class Evidence(Model):
    kind: EvidenceKind
    source: str
    summary: str
    line: int | None = None

    def __post_init__(self) -> None:
        _require_text("Evidence.source", self.source)
        _require_text("Evidence.summary", self.summary)
        if self.line is not None and self.line < 1:
            raise ModelError("Evidence.line must be >= 1")


@dataclass(frozen=True, kw_only=True)
class UnknownFact(Model):
    subject: str
    missing: str
    resolution: str

    def __post_init__(self) -> None:
        _require_text("UnknownFact.subject", self.subject)
        _require_text("UnknownFact.missing", self.missing)
        _require_text("UnknownFact.resolution", self.resolution)


@dataclass(frozen=True, kw_only=True)
class Finding(Model):
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    evidence: tuple[Evidence, ...] = ()
    entity_ids: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    def __post_init__(self) -> None:
        _require_text("Finding.id", self.id)
        _require_text("Finding.title", self.title)


@dataclass(frozen=True, kw_only=True)
class Entity(Model):
    id: str
    kind: str
    name: str
    attributes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("Entity.kind", self.kind)
        _require_text("Entity.name", self.name)
        parts = self.id.split(":", 2) if isinstance(self.id, str) else []
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ModelError(f"Entity.id must be '{{kind}}:{{domain}}:{{identifier}}': {self.id!r}")
        if parts[0] != self.kind:
            raise ModelError(f"Entity.id kind {parts[0]!r} does not match kind {self.kind!r}")


@dataclass(frozen=True, kw_only=True)
class Relationship(Model):
    kind: str
    source_id: str
    target_id: str
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        _require_text("Relationship.kind", self.kind)
        _require_text("Relationship.source_id", self.source_id)
        _require_text("Relationship.target_id", self.target_id)


@dataclass(frozen=True, kw_only=True)
class Capability(Model):
    id: str
    name: str
    confidence: Confidence
    entity_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("Capability.id", self.id)
        _require_text("Capability.name", self.name)


@dataclass(frozen=True, kw_only=True)
class CapabilityDependency(Model):
    capability_id: str
    depends_on_id: str
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        _require_text("CapabilityDependency.capability_id", self.capability_id)
        _require_text("CapabilityDependency.depends_on_id", self.depends_on_id)
        if self.capability_id == self.depends_on_id:
            raise ModelError("CapabilityDependency must not depend on itself")


@dataclass(frozen=True, kw_only=True)
class RuntimeEvidence(Model):
    entity_id: str
    metric: str
    value: float
    unit: str
    source: str
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("RuntimeEvidence.entity_id", self.entity_id)
        _require_text("RuntimeEvidence.metric", self.metric)
        _require_finite("RuntimeEvidence.value", self.value)
        _require_text("RuntimeEvidence.unit", self.unit)
        _require_text("RuntimeEvidence.source", self.source)
        _require_aware("RuntimeEvidence.observed_at", self.observed_at)


@dataclass(frozen=True, kw_only=True)
class ChangeEvent(Model):
    id: str
    kind: str
    description: str
    entity_ids: tuple[str, ...] = ()
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("ChangeEvent.id", self.id)
        _require_text("ChangeEvent.kind", self.kind)
        _require_text("ChangeEvent.description", self.description)
        _require_aware("ChangeEvent.occurred_at", self.occurred_at)


@dataclass(frozen=True, kw_only=True)
class Baseline(Model):
    entity_id: str
    metric: str
    value: float
    unit: str
    sample_count: int
    window: str

    def __post_init__(self) -> None:
        _require_text("Baseline.entity_id", self.entity_id)
        _require_text("Baseline.metric", self.metric)
        _require_finite("Baseline.value", self.value)
        _require_text("Baseline.unit", self.unit)
        _require_text("Baseline.window", self.window)
        if self.sample_count < 0:
            raise ModelError("Baseline.sample_count must be >= 0")


@dataclass(frozen=True, kw_only=True)
class Regression(Model):
    entity_id: str
    metric: str
    baseline_value: float
    observed_value: float
    unit: str
    confidence: Confidence

    def __post_init__(self) -> None:
        _require_text("Regression.entity_id", self.entity_id)
        _require_text("Regression.metric", self.metric)
        _require_finite("Regression.baseline_value", self.baseline_value)
        _require_finite("Regression.observed_value", self.observed_value)
        _require_text("Regression.unit", self.unit)


@dataclass(frozen=True, kw_only=True)
class SLO(Model):
    id: str
    entity_id: str
    objective: str
    target: float
    unit: str
    window: str

    def __post_init__(self) -> None:
        _require_text("SLO.id", self.id)
        _require_text("SLO.entity_id", self.entity_id)
        _require_text("SLO.objective", self.objective)
        _require_finite("SLO.target", self.target)
        _require_text("SLO.unit", self.unit)
        _require_text("SLO.window", self.window)


@dataclass(frozen=True, kw_only=True)
class Remediation(Model):
    id: str
    finding_id: str
    summary: str
    safety: RemediationSafety

    def __post_init__(self) -> None:
        _require_text("Remediation.id", self.id)
        _require_text("Remediation.finding_id", self.finding_id)
        _require_text("Remediation.summary", self.summary)


@dataclass(frozen=True, kw_only=True)
class Experiment(Model):
    id: str
    hypothesis: str
    change: str
    entity_ids: tuple[str, ...] = ()
    verdict: ExperimentVerdict | None = None

    def __post_init__(self) -> None:
        _require_text("Experiment.id", self.id)
        _require_text("Experiment.hypothesis", self.hypothesis)
        _require_text("Experiment.change", self.change)


@dataclass(frozen=True, kw_only=True)
class DecisionContext(Model):
    question: str
    facts: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    tradeoffs: tuple[str, ...] = ()
    unknowns: tuple[UnknownFact, ...] = ()

    def __post_init__(self) -> None:
        _require_text("DecisionContext.question", self.question)
