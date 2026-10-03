"""Core universal models (§5).

All models are frozen dataclasses with deterministic serialization:
keys are emitted in sorted order, mappings are sorted, datetimes are
normalized to UTC, and unordered collections (sets) are rejected so that
iteration order can never leak into output. No model reads the clock;
timestamps must be injected by the caller. Every serialized payload passes
through `redaction.redact` (§57, §125); free-text fields of the evidence and
finding contracts are additionally redacted at construction.
"""

from __future__ import annotations

import json
import math
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any, Self, Union, cast, get_args, get_origin, get_type_hints

from forge_doctor_api.core.redaction import redact, redact_text


class ModelError(ValueError):
    """Raised when a model is constructed or decoded from invalid data."""


class EvidenceKind(StrEnum):
    """Where a fact came from (§6). Every finding must declare one.

    - STATIC: source code, AST, interface definitions (OpenAPI, proto, schema).
    - CONFIG: gateway, deployment, and policy configuration.
    - OBSERVED_METADATA: exported artifacts and inventories.
    - RUNTIME: logs, metrics, traces.
    - DERIVED: correlation of other facts; never stronger than its inputs.
    """

    STATIC = "STATIC"
    CONFIG = "CONFIG"
    OBSERVED_METADATA = "OBSERVED_METADATA"
    RUNTIME = "RUNTIME"
    DERIVED = "DERIVED"


class Confidence(StrEnum):
    """How strongly the evidence supports a claim.

    - HIGH: direct, unambiguous evidence; a false positive would be a bug.
    - MEDIUM: strong evidence with a known gap (e.g. only one side of a contract).
    - LOW: heuristic or indirect evidence; surface as a candidate only.
    - UNKNOWN: evidence is insufficient to decide. A first-class state, not an
      error path: a finding at UNKNOWN must list the `UnknownFact`s that would
      resolve it instead of guessing (§145).
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class Severity(StrEnum):
    """Impact if the finding is real, independent of confidence.

    - CRITICAL: breaks clients, leaks data, or blocks a release now.
    - HIGH: likely production impact or security exposure.
    - MEDIUM: correctness or contract-quality issue with bounded impact.
    - LOW: hygiene issue; cheap to fix, small impact.
    - INFO: observation with no direct impact.

    There is no UNKNOWN severity: uncertainty is expressed through
    `Confidence.UNKNOWN` plus `UnknownFact`s, keeping impact and certainty
    orthogonal.
    """

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
        return value._encode_fields()
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


def _require_enum(name: str, value: object, enum: type[Enum]) -> None:
    if not isinstance(value, enum):
        raise ModelError(f"{name} must be a {enum.__name__}, got {value!r}")


def _redact_attrs(obj: object, *names: str) -> None:
    for name in names:
        value = getattr(obj, name)
        if isinstance(value, str):
            object.__setattr__(obj, name, redact_text(value))


@dataclass(frozen=True, kw_only=True)
class Model:
    """Base for all core models: deterministic, redacted dict/JSON round-trip."""

    def _encode_fields(self) -> dict[str, Any]:
        return {f.name: _encode(getattr(self, f.name)) for f in sorted(fields(self), key=_name)}

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], redact(self._encode_fields()))

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


CHECK_ID_PATTERN = re.compile(r"^(?P<namespace>[A-Z]{2,10})(?P<number>[0-9]{3,4})$")


def check_namespace(check_id: str) -> str:
    """Return the namespace prefix of a stable check id (`OAS001` -> `OAS`)."""
    match = CHECK_ID_PATTERN.match(check_id) if isinstance(check_id, str) else None
    if match is None:
        raise ModelError(
            f"check id must be an uppercase namespace followed by 3-4 digits: {check_id!r}"
        )
    return match["namespace"]


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
        _require_enum("Evidence.kind", self.kind, EvidenceKind)
        if self.line is not None and self.line < 1:
            raise ModelError("Evidence.line must be >= 1")
        _redact_attrs(self, "source", "summary")


@dataclass(frozen=True, kw_only=True)
class SourceLocation(Model):
    """Project-relative POSIX path plus optional 1-based line and column."""

    path: str
    line: int | None = None
    column: int | None = None

    def __post_init__(self) -> None:
        _require_text("SourceLocation.path", self.path)
        if "\\" in self.path:
            raise ModelError("SourceLocation.path must use '/' separators")
        if self.line is not None and self.line < 1:
            raise ModelError("SourceLocation.line must be >= 1")
        if self.column is not None and (self.line is None or self.column < 1):
            raise ModelError("SourceLocation.column must be >= 1 and requires line")
        _redact_attrs(self, "path")


@dataclass(frozen=True, kw_only=True)
class UnknownFact(Model):
    """A fact the engine could not establish: what is missing, what resolves it."""

    subject: str
    missing: str
    resolution: str

    def __post_init__(self) -> None:
        _require_text("UnknownFact.subject", self.subject)
        _require_text("UnknownFact.missing", self.missing)
        _require_text("UnknownFact.resolution", self.resolution)
        _redact_attrs(self, "subject", "missing", "resolution")


@dataclass(frozen=True, kw_only=True)
class Finding(Model):
    """A check result. `id` is the stable namespaced check id (e.g. `OAS001`).

    `entity_ids` are the affected entity refs; `remediation` is a short hint,
    not an applied fix. A finding at `Confidence.UNKNOWN` must carry at least
    one `UnknownFact` explaining what evidence is missing.
    """

    id: str
    title: str
    description: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    evidence: tuple[Evidence, ...] = ()
    entity_ids: tuple[str, ...] = ()
    source_location: SourceLocation | None = None
    remediation: str | None = None
    unknowns: tuple[UnknownFact, ...] = ()

    def __post_init__(self) -> None:
        check_namespace(self.id)
        _require_text("Finding.title", self.title)
        _require_text("Finding.description", self.description)
        _require_enum("Finding.severity", self.severity, Severity)
        _require_enum("Finding.confidence", self.confidence, Confidence)
        _require_enum("Finding.evidence_kind", self.evidence_kind, EvidenceKind)
        if self.remediation is not None:
            _require_text("Finding.remediation", self.remediation)
        if self.confidence is Confidence.UNKNOWN and not self.unknowns:
            raise ModelError("Finding with UNKNOWN confidence must list its unknowns")
        _redact_attrs(self, "title", "description", "remediation")

    @property
    def namespace(self) -> str:
        return check_namespace(self.id)


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
