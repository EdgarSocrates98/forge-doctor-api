"""OAS### check catalog (§11, §218).

Every check has a stable id, a default severity/confidence, an evidence kind,
and a documented trigger condition. Ids are never renumbered; per-finding
severity/confidence may be tightened by the engine when the trigger warrants
it. Checks whose trigger needs organization context (exposure, ownership,
environments) emit LOW-confidence candidates carrying `UnknownFact`s instead
of asserting violations (§101, §145).
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Confidence, EvidenceKind, ModelError, Severity

S = Severity
C = Confidence


@dataclass(frozen=True)
class CheckSpec:
    id: str
    title: str
    severity: Severity
    confidence: Confidence
    evidence_kind: EvidenceKind
    trigger: str

    def __post_init__(self) -> None:
        if not self.id.startswith("OAS"):
            raise ModelError(f"check id must be in the OAS namespace: {self.id!r}")


CATALOG: tuple[CheckSpec, ...] = (
    CheckSpec(
        id="OAS001",
        title="Invalid specification version",
        severity=S.HIGH,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A document carrying the `openapi` marker fails to load as a supported spec: "
            "unparseable (MALFORMED), unreadable (UNREADABLE), a version field that is not "
            "MAJOR.MINOR.PATCH (INVALID_VERSION), or a version outside the bundled knowledge "
            "pack (UNSUPPORTED_VERSION, e.g. Swagger 2.0)."
        ),
    ),
    CheckSpec(
        id="OAS002",
        title="Unresolved local reference",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A `$ref` whose target file or JSON pointer does not exist (MISSING), or whose "
            "reference string is malformed (INVALID). External URL refs are never fetched "
            "and never reported here."
        ),
    ),
    CheckSpec(
        id="OAS003",
        title="Duplicate operationId",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "The same non-empty `operationId` names two or more operations across the "
            "parsed documents."
        ),
    ),
    CheckSpec(
        id="OAS004",
        title="Operation without operationId",
        severity=S.LOW,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A path operation has no `operationId`. Callback and webhook operations are "
            "exempt: they are name-addressed rather than id-addressed."
        ),
    ),
    CheckSpec(
        id="OAS005",
        title="Undocumented response",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A response object without the spec-required `description`, or an operation "
            "that declares no responses at all. Unresolved `$ref` responses are skipped: "
            "their description is UNKNOWN, not missing."
        ),
    ),
    CheckSpec(
        id="OAS006",
        title="Default-only response",
        severity=S.LOW,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger="An operation declares exactly one response and it is the `default` response.",
    ),
    CheckSpec(
        id="OAS007",
        title="Inconsistent error schema",
        severity=S.MEDIUM,
        confidence=C.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "Within one document, at least 3 operations declare 4xx/5xx schemas and a strict "
            "majority (>=60%) share one schema shape; operations deviating from the dominant "
            "shape are reported. Below those thresholds the evidence is too weak to fire."
        ),
    ),
    CheckSpec(
        id="OAS008",
        title="Request body missing schema",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A request body whose `content` exists but has no `schema`, or a `requestBody` "
            "object with no `content` at all. Unresolved `$ref` bodies are skipped."
        ),
    ),
    CheckSpec(
        id="OAS009",
        title="Response missing schema",
        severity=S.LOW,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A response that declares `content` media types without a `schema` under any of "
            "them. Content-free responses (e.g. 204) and unresolved `$ref`s are skipped."
        ),
    ),
    CheckSpec(
        id="OAS010",
        title="Public API without security requirement (candidate)",
        severity=S.HIGH,
        confidence=C.LOW,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A document with operations has no document-level `security` requirement, or "
            "every document-level requirement is anonymous (`{}`). Emitted as a LOW-"
            "confidence candidate: whether the API is public is organization context the "
            "parser cannot see."
        ),
    ),
    CheckSpec(
        id="OAS011",
        title="Operation overrides security unexpectedly",
        severity=S.MEDIUM,
        confidence=C.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "An operation's own `security` makes the operation anonymous while the document "
            "requires named schemes (auth opt-out), or any security requirement references a "
            "scheme not defined in the document's `components.securitySchemes`."
        ),
    ),
    CheckSpec(
        id="OAS012",
        title="Path parameter mismatch",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A declared `in: path` parameter whose name is absent from the path template, a "
            "template `{var}` declared with a different `in`, or a template variable declared "
            "`in: path` without `required: true`."
        ),
    ),
    CheckSpec(
        id="OAS013",
        title="Required path parameter not declared",
        severity=S.HIGH,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A `{var}` in a path template has no parameter declaration of that name anywhere "
            "in the operation or its path item. A same-named parameter declared with the "
            "wrong `in` is OAS012, not OAS013 — one variable never double-reports."
        ),
    ),
    CheckSpec(
        id="OAS014",
        title="Schema without type information",
        severity=S.LOW,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A component schema object carrying none of: type, $ref, properties, items, "
            "enum, const, allOf, anyOf, oneOf, not, format, additionalProperties, "
            "patternProperties, prefixItems. Boolean schemas are exempt."
        ),
    ),
    CheckSpec(
        id="OAS015",
        title="Deprecated API without sunset metadata",
        severity=S.LOW,
        confidence=C.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "An operation marked `deprecated: true` with no sunset signal in its document: "
            "no x-sunset*/x-deprecation* extension on the document, path item or operation, "
            "and no Sunset/Deprecation response header."
        ),
    ),
    CheckSpec(
        id="OAS016",
        title="Server URL environment mismatch (candidate)",
        severity=S.LOW,
        confidence=C.LOW,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "One document's servers span more than one environment class (local / dev / "
            "staging / other). Parameterized URLs like `{env}.example.com` are skipped. "
            "LOW-confidence candidate: environment policy is organization context."
        ),
    ),
    CheckSpec(
        id="OAS017",
        title="Unrestricted additionalProperties (candidate)",
        severity=S.LOW,
        confidence=C.LOW,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A component schema uses `additionalProperties: true` (or an empty schema), "
            "which permits arbitrary keys. LOW-confidence candidate: free-form maps are "
            "often intended."
        ),
    ),
    CheckSpec(
        id="OAS018",
        title="Unused component schema",
        severity=S.INFO,
        confidence=C.MEDIUM,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A `components.schemas` entry is never the target of a resolved `$ref` in the "
            "project. MEDIUM confidence: schemas can be referenced dynamically or from "
            "outside the scanned project."
        ),
    ),
    CheckSpec(
        id="OAS019",
        title="Circular reference depth risk",
        severity=S.MEDIUM,
        confidence=C.HIGH,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A recorded reference cycle: ALIAS cycles (chains of `$ref` objects that never "
            "reach a concrete object) are defects; RECURSIVE cycles (self-referential "
            "structures) are legal but flagged so consumers bound traversal depth."
        ),
    ),
    CheckSpec(
        id="OAS020",
        title="Operation without tags/domain ownership (candidate)",
        severity=S.INFO,
        confidence=C.LOW,
        evidence_kind=EvidenceKind.STATIC,
        trigger=(
            "A path operation has no `tags`, so no domain grouping can be evidenced from "
            "the contract. LOW-confidence candidate: ownership may live outside the spec."
        ),
    ),
)

BY_ID: dict[str, CheckSpec] = {spec.id: spec for spec in CATALOG}
