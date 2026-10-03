"""`ApiCompatibilityEngine` (§16): semantic diff of two OpenAPI models.

Produces a typed `ContractChange` list classified per §16.1 and `Finding`s in
the `COMPAT###` namespace. Request-side and response-side compatibility are
evaluated separately (§123): narrowing what the *client may send* is breaking
in the opposite direction from narrowing what the *client receives*.

- Request side: the contract constrains client input. Narrower (new required
  fields, removed enum values, tighter types) = BREAKING; wider = candidate.
- Response side: the contract constrains server output. Removed fields or
  narrowed types = BREAKING; added fields/widened types = POTENTIALLY
  BREAKING because strictly-decoding clients may still fail (§16.3).
- Anything the model cannot decompose (unresolved refs, composition changes,
  missing schema content) is classified UNKNOWN, never guessed (§16.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from forge_doctor_api.analyzers.openapi.model import (
    DocumentStatus,
    OpenApiOperation,
    OpenApiParameter,
    OpenApiProjectModel,
    OpenApiRequestBody,
    OpenApiResponse,
    OperationSource,
)
from forge_doctor_api.checks.compat.catalog import (
    CHANGE_TO_SPEC,
    ChangeSide,
    CompatCheckSpec,
    CompatibilityClass,
)
from forge_doctor_api.checks.drift import normalize_path
from forge_doctor_api.core.models import (
    Confidence,
    Evidence,
    EvidenceKind,
    Finding,
    Model,
    SourceLocation,
    UnknownFact,
)

_COMPOSITION = ("allOf", "anyOf", "oneOf")
_MAX_DEPTH = 12


@dataclass(frozen=True, kw_only=True)
class ContractChange(Model):
    """One semantic diff entry. `path` is the §122 field path."""

    kind: str
    classification: CompatibilityClass
    side: ChangeSide
    subject: str
    path: str
    detail: str
    before: str | None = None
    after: str | None = None
    location: SourceLocation | None = None


@dataclass(frozen=True, kw_only=True)
class ContractDiff(Model):
    changes: tuple[ContractChange, ...] = ()
    findings: tuple[Finding, ...] = ()


def _finding(spec: CompatCheckSpec, change: ContractChange) -> Finding:
    unknown = change.classification is CompatibilityClass.UNKNOWN
    return Finding(
        id=spec.id,
        title=spec.title,
        description=change.detail,
        severity=spec.severity,
        confidence=Confidence.UNKNOWN if unknown else spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=EvidenceKind.STATIC,
                source=change.location.path,
                summary=change.detail,
                line=change.location.line,
            ),
        )
        if change.location is not None
        else (),
        entity_ids=(change.subject,) if change.subject.startswith("operation:") else (),
        source_location=change.location,
        unknowns=(
            UnknownFact(
                subject=change.path,
                missing="enough schema detail to decompose this change",
                resolution="resolve the changed structures concretely in the contract",
            ),
        )
        if unknown
        else (),
    )


def _type_set(schema: dict[str, Any]) -> frozenset[str]:
    t = schema.get("type")
    if isinstance(t, str):
        return frozenset({t})
    if isinstance(t, list):
        return frozenset(str(x) for x in t)
    return frozenset()


def _is_subset(small: frozenset[str], big: frozenset[str]) -> bool:
    """Subset including the integer ⊆ number widening edge."""
    if small <= big:
        return True
    return {("number" if t == "integer" else t) for t in small} <= big


def _required_names(schema: dict[str, Any]) -> frozenset[str]:
    req = schema.get("required")
    return frozenset(str(x) for x in req) if isinstance(req, list) else frozenset()


def _resolve(schema: Any, schemas: dict[str, Any]) -> Any:
    """Unwrap a single local `$ref` hop to component content."""
    if isinstance(schema, dict) and isinstance(schema.get("$ref"), str):
        ref = schema["$ref"]
        if ref.startswith("#/components/schemas/"):
            return schemas.get(ref.rsplit("/", 1)[-1], schema)
        return schema
    return schema


class _SchemaDiff:
    """Recursive schema comparer keyed by §122 field paths."""

    def __init__(
        self,
        schemas: dict[str, Any],
        subject: str,
        side: ChangeSide,
        location: SourceLocation | None,
    ) -> None:
        self.schemas = schemas
        self.subject = subject
        self.side = side
        self.location = location
        self.out: list[ContractChange] = []

    def emit(
        self,
        kind: str,
        classification: CompatibilityClass,
        path: str,
        detail: str,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self.out.append(
            ContractChange(
                kind=kind,
                classification=classification,
                side=self.side,
                subject=self.subject,
                path=path,
                detail=detail,
                before=before,
                after=after,
                location=self.location,
            )
        )

    def unknown(self, path: str, detail: str) -> None:
        self.emit("unresolvable", CompatibilityClass.UNKNOWN, path, detail)

    def diff(self, old: Any, new: Any, path: str, depth: int = 0) -> None:
        if depth > _MAX_DEPTH:
            self.unknown(path, "schema deeper than the traversal bound")
            return
        old = _resolve(old, self.schemas)
        new = _resolve(new, self.schemas)
        if old == new:
            return
        if old is None or new is None:
            self.unknown(path, f"schema present on one side only ({old!r} -> {new!r})")
            return
        o_ref = old.get("$ref") if isinstance(old, dict) else None
        n_ref = new.get("$ref") if isinstance(new, dict) else None
        if isinstance(o_ref, str) or isinstance(n_ref, str):
            if o_ref != n_ref:
                self.emit(
                    f"type_changed_{self.side.value}",
                    CompatibilityClass.BREAKING,
                    path,
                    f"{path}: ref target changed {o_ref} -> {n_ref}",
                    str(o_ref)[:60],
                    str(n_ref)[:60],
                )
            return
        if not isinstance(old, dict) or not isinstance(new, dict):
            self.emit(
                f"type_changed_{self.side.value}",
                CompatibilityClass.BREAKING,
                path,
                f"{path}: schema changed {old!r} -> {new!r}",
                str(old)[:60],
                str(new)[:60],
            )
            return
        for keyword in _COMPOSITION:
            o, n = old.get(keyword), new.get(keyword)
            if (o is None) != (n is None) or (
                isinstance(o, list) and isinstance(n, list) and len(o) != len(n)
            ):
                self.unknown(
                    path, f"composition keyword {keyword} changed; cannot decompose safely"
                )
                return
            if isinstance(o, list) and isinstance(n, list):
                o_sorted = sorted(o, key=repr)
                n_sorted = sorted(n, key=repr)
                for index, (a, b) in enumerate(zip(o_sorted, n_sorted, strict=True)):
                    self.diff(a, b, f"{path}.{keyword}[{index}]", depth + 1)
        self._types(old, new, path)
        self._enums(old, new, path)
        self._required(old, new, path)
        self._properties(old, new, path, depth)
        self._items(old, new, path, depth)
        self._additional(old, new, path, depth)

    def _types(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        o_fmt, n_fmt = old.get("format"), new.get("format")
        if o_fmt != n_fmt and (o_fmt is not None or n_fmt is not None):
            self.emit(
                f"type_changed_{self.side.value}",
                CompatibilityClass.POTENTIALLY_BREAKING,
                path,
                f"{path}: format changed {o_fmt!r} -> {n_fmt!r}",
            )
        o, n = _type_set(old), _type_set(new)
        if not o or not n or o == n:
            return
        narrowed = _is_subset(n, o)
        widened = _is_subset(o, n)
        if narrowed and not widened:
            self.emit(
                f"type_changed_{self.side.value}",
                CompatibilityClass.BREAKING,
                path,
                f"{path}: type narrowed {sorted(o)} -> {sorted(n)}",
                ",".join(sorted(o)),
                ",".join(sorted(n)),
            )
        elif widened and not narrowed:
            if self.side is not ChangeSide.REQUEST:
                self.emit(
                    "response_type_widened",
                    CompatibilityClass.POTENTIALLY_BREAKING,
                    path,
                    f"{path}: response type widened {sorted(o)} -> {sorted(n)}",
                    ",".join(sorted(o)),
                    ",".join(sorted(n)),
                )
        else:
            self.emit(
                f"type_changed_{self.side.value}",
                CompatibilityClass.BREAKING,
                path,
                f"{path}: type changed {sorted(o)} -> {sorted(n)}",
                ",".join(sorted(o)),
                ",".join(sorted(n)),
            )

    def _enums(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        o, n = old.get("enum"), new.get("enum")
        if not isinstance(o, list) or not isinstance(n, list):
            return
        removed = sorted({str(v) for v in o} - {str(v) for v in n})
        added = sorted({str(v) for v in n} - {str(v) for v in o})
        if removed:
            self.emit(
                "enum_removed",
                CompatibilityClass.BREAKING,
                path,
                f"{path}: enum values removed: {removed}",
            )
        if added:
            self.emit(
                "enum_added",
                CompatibilityClass.POTENTIALLY_BREAKING,
                path,
                f"{path}: enum values added: {added}",
            )

    def _required(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        o, n = _required_names(old), _required_names(new)
        if self.side is not ChangeSide.REQUEST:
            return  # response-side required only constrains the server
        for name in sorted(n - o):
            self.emit(
                "request_field_required",
                CompatibilityClass.BREAKING,
                f"{path}.{name}",
                f"{path}.{name}: request field became required",
            )

    def _properties(
        self, old: dict[str, Any], new: dict[str, Any], path: str, depth: int
    ) -> None:
        o_raw, n_raw = old.get("properties"), new.get("properties")
        o: dict[str, Any] = o_raw if isinstance(o_raw, dict) else {}
        n: dict[str, Any] = n_raw if isinstance(n_raw, dict) else {}
        new_required = _required_names(new)
        for name in sorted(set(o) - set(n)):
            if self.side is ChangeSide.RESPONSE:
                self.emit(
                    "response_field_removed",
                    CompatibilityClass.BREAKING,
                    f"{path}.{name}",
                    f"{path}.{name}: response field removed",
                )
            else:
                self.emit(
                    "request_field_removed",
                    CompatibilityClass.POTENTIALLY_BREAKING,
                    f"{path}.{name}",
                    f"{path}.{name}: request field no longer declared",
                )
        for name in sorted(set(n) - set(o)):
            if self.side is ChangeSide.RESPONSE:
                self.emit(
                    "response_field_added",
                    CompatibilityClass.POTENTIALLY_BREAKING,
                    f"{path}.{name}",
                    f"{path}.{name}: response field added"
                    + (" (required)" if name in new_required else " (optional)"),
                )
            elif name not in new_required:
                self.emit(
                    "request_field_added",
                    CompatibilityClass.POTENTIALLY_BREAKING,
                    f"{path}.{name}",
                    f"{path}.{name}: optional request field added",
                )
            # required request fields are already emitted by _required
        for name in sorted(set(o) & set(n)):
            self.diff(o[name], n[name], f"{path}.{name}", depth + 1)

    def _items(
        self, old: dict[str, Any], new: dict[str, Any], path: str, depth: int
    ) -> None:
        o, n = old.get("items"), new.get("items")
        if o is None and n is None:
            return
        if o is None or n is None:
            self.unknown(f"{path}[]", "items appeared or disappeared")
            return
        self.diff(o, n, f"{path}[]", depth + 1)

    def _additional(
        self, old: dict[str, Any], new: dict[str, Any], path: str, depth: int
    ) -> None:
        o, n = old.get("additionalProperties"), new.get("additionalProperties")
        if o == n or (o is None and n is None):
            return
        o_free = o is None or o is True or o == {}
        n_free = n is None or n is True or n == {}
        if o_free and n_free:
            return  # absent and `true` are both "free" — semantically identical
        if o_free and not n_free:
            if self.side is ChangeSide.REQUEST:
                self.emit(
                    "type_changed_request",
                    CompatibilityClass.BREAKING,
                    path,
                    f"{path}: additionalProperties tightened {o!r} -> {n!r}",
                )
            else:
                self.emit(
                    "type_changed_response",
                    CompatibilityClass.BREAKING,
                    path,
                    f"{path}: additionalProperties narrowed {o!r} -> {n!r}",
                )
        elif n_free and not o_free:
            if self.side is ChangeSide.RESPONSE:
                self.emit(
                    "response_type_widened",
                    CompatibilityClass.POTENTIALLY_BREAKING,
                    path,
                    f"{path}: additionalProperties relaxed {o!r} -> {n!r}",
                )
        elif isinstance(o, dict) and isinstance(n, dict):
            self.diff(o, n, f"{path}.*", depth + 1)
        else:
            self.unknown(
                path, f"additionalProperties changed {o!r} -> {n!r}; direction unclear"
            )


def diff_schema_content(
    old: Any,
    new: Any,
    *,
    side: ChangeSide,
    subject: str,
    path: str = "schema",
    schemas: dict[str, Any] | None = None,
    location: SourceLocation | None = None,
) -> tuple[ContractChange, ...]:
    """Public schema-content diff for non-OpenAPI callers (§121 unified engine).

    `schemas` maps component names to raw content for `$ref` resolution.
    Request side = the writer's contract; response side = the reader's view.
    """
    differ = _SchemaDiff(schemas or {}, subject, side, location)
    differ.diff(old, new, path)
    return tuple(differ.out)


def _op_key(op: OpenApiOperation) -> tuple[str, str]:
    return op.method, normalize_path(op.path)


def _ref_name(shape: str) -> str | None:
    match = re.match(r"^ref:#/components/schemas/(?P<name>.+)$", shape)
    return match["name"] if match else None


def _effective_security(
    requirements: dict[tuple[str, str], list[frozenset[str]]],
    op: OpenApiOperation,
) -> frozenset[frozenset[str]]:
    """Effective auth alternatives: op-level overrides root (``security: []`` included).

    Absence of any recorded requirement means anonymous access, modeled as the
    single empty alternative.
    """
    if op.has_security:
        alts = requirements.get((op.pointer, op.location.path), [])
    else:
        alts = requirements.get(("", op.location.path), [])
    return frozenset(alts) or frozenset({frozenset()})


def _requirement_table(model: OpenApiProjectModel) -> dict[tuple[str, str], list[frozenset[str]]]:
    table: dict[tuple[str, str], list[frozenset[str]]] = {}
    for req in model.security_requirements:
        key = (req.owner_pointer, req.location.path)
        table.setdefault(key, []).append(frozenset(s.name for s in req.schemes))
    return table


def _shape_names(shapes: tuple[str, ...]) -> frozenset[str]:
    return frozenset(name for s in shapes if (name := _ref_name(s)))


def _diff_schemas_by_shape(
    o_shapes: tuple[str, ...],
    n_shapes: tuple[str, ...],
    old_schemas: dict[str, Any],
    new_schemas: dict[str, Any],
    side: ChangeSide,
    subject: str,
    path: str,
    location: SourceLocation | None,
    out: list[ContractChange],
) -> None:
    """Deep-diff schema content via ref names; UNKNOWN when not decomposable.

    Ref names resolve to the *current* content in each model, so the same
    `ref:` token can still hide a content change — always diff resolved
    content, not just shapes.
    """
    o_names = _shape_names(o_shapes)
    n_names = _shape_names(n_shapes)
    if not o_names and not n_names:
        if o_shapes == n_shapes:
            return  # identical inline shapes: nothing detectable changed
        out.append(
            ContractChange(
                kind="unresolvable",
                classification=CompatibilityClass.UNKNOWN,
                side=side,
                subject=subject,
                path=path,
                detail=(
                    f"{subject}: {path} schema changed ({sorted(o_shapes)} -> "
                    f"{sorted(n_shapes)}) but has no resolvable refs"
                ),
                location=location,
            )
        )
        return
    pairs: list[tuple[str, str]] = []
    if o_names == n_names:
        pairs = [(name, name) for name in sorted(o_names)]
    elif len(o_names ^ n_names) == 2:
        # exactly one ref renamed; diff old target against new target
        (o_only,) = sorted(o_names - n_names)
        (n_only,) = sorted(n_names - o_names)
        pairs = [(name, name) for name in sorted(o_names & n_names)] + [(o_only, n_only)]
    else:
        out.append(
            ContractChange(
                kind="unresolvable",
                classification=CompatibilityClass.UNKNOWN,
                side=side,
                subject=subject,
                path=path,
                detail=(
                    f"{subject}: {path} ref targets changed {sorted(o_names)} -> "
                    f"{sorted(n_names)}; cannot align safely"
                ),
                location=location,
            )
        )
        return
    for o_name, n_name in pairs:
        differ = _SchemaDiff(new_schemas, subject, side, location)
        differ.diff(
            old_schemas.get(o_name),
            new_schemas.get(n_name),
            f"{path}:{n_name}" if o_name == n_name else f"{path}:{o_name}->{n_name}",
        )
        out.extend(differ.out)


def diff_models(old: OpenApiProjectModel, new: OpenApiProjectModel) -> ContractDiff:
    old_ops = {(_op_key(o)): o for o in old.operations if o.source is OperationSource.PATH}
    new_ops = {(_op_key(o)): o for o in new.operations if o.source is OperationSource.PATH}
    old_params = {(p.location.path, p.pointer): p for p in old.parameters}
    new_params = {(p.location.path, p.pointer): p for p in new.parameters}
    old_bodies = {(b.location.path, b.pointer): b for b in old.request_bodies}
    new_bodies = {(b.location.path, b.pointer): b for b in new.request_bodies}
    old_responses = {(r.location.path, r.pointer): r for r in old.responses}
    new_responses = {(r.location.path, r.pointer): r for r in new.responses}
    old_schemas = {s.name: s.content for s in old.schemas}
    new_schemas = {s.name: s.content for s in new.schemas}
    old_reqs = _requirement_table(old)
    new_reqs = _requirement_table(new)

    changes: list[ContractChange] = []

    for label, model in (("old", old), ("new", new)):
        bad = [
            d
            for d in model.documents
            if d.status
            in (
                DocumentStatus.MALFORMED,
                DocumentStatus.UNREADABLE,
                DocumentStatus.INVALID_VERSION,
                DocumentStatus.UNSUPPORTED_VERSION,
            )
        ]
        for doc in bad:
            changes.append(
                ContractChange(
                    kind="unresolvable",
                    classification=CompatibilityClass.UNKNOWN,
                    side=ChangeSide.META,
                    subject="",
                    path=doc.location.path,
                    detail=(
                        f"{label} contract {doc.location.path} has status "
                        f"{doc.status.value}; diff evidence is incomplete"
                    ),
                    location=doc.location,
                )
            )

    old_paths = {p for _, p in old_ops}
    new_paths = {p for _, p in new_ops}
    for path in sorted(old_paths - new_paths):
        ops = sorted((o for (m, p), o in old_ops.items() if p == path), key=lambda o: o.method)
        changes.append(
            ContractChange(
                kind="endpoint_removed",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.META,
                subject=ops[0].identity if ops else "",
                path=path,
                detail=f"endpoint removed: {path} ({', '.join(o.method for o in ops)})",
                location=ops[0].location if ops else None,
            )
        )
    for path in sorted(new_paths - old_paths):
        ops = sorted((o for (m, p), o in new_ops.items() if p == path), key=lambda o: o.method)
        changes.append(
            ContractChange(
                kind="endpoint_added",
                classification=CompatibilityClass.POTENTIALLY_BREAKING,
                side=ChangeSide.META,
                subject=ops[0].identity if ops else "",
                path=path,
                detail=f"endpoint added: {path} ({', '.join(o.method for o in ops)})",
                location=ops[0].location if ops else None,
            )
        )
    for path in sorted(old_paths & new_paths):
        old_methods = {m for (m, p) in old_ops if p == path}
        new_methods = {m for (m, p) in new_ops if p == path}
        for method in sorted(old_methods - new_methods):
            op = old_ops[(method, path)]
            changes.append(
                ContractChange(
                    kind="method_removed",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.META,
                    subject=op.identity,
                    path=path,
                    detail=f"method removed: {method} {path}",
                    location=op.location,
                )
            )
        for method in sorted(new_methods - old_methods):
            op = new_ops[(method, path)]
            changes.append(
                ContractChange(
                    kind="endpoint_added",
                    classification=CompatibilityClass.POTENTIALLY_BREAKING,
                    side=ChangeSide.META,
                    subject=op.identity,
                    path=path,
                    detail=f"method added: {method} {path}",
                    location=op.location,
                )
            )

    for key in sorted(set(old_ops) & set(new_ops)):
        changes.extend(
            _diff_operation(
                old_ops[key],
                new_ops[key],
                old_params,
                new_params,
                old_bodies,
                new_bodies,
                old_responses,
                new_responses,
                old_schemas,
                new_schemas,
                old_reqs,
                new_reqs,
            )
        )

    ordered = tuple(sorted(changes, key=lambda c: (c.kind, c.subject, c.path, c.detail)))
    findings = sorted(
        (
            _finding(CHANGE_TO_SPEC[c.kind], c)
            for c in ordered
            if c.kind in CHANGE_TO_SPEC
        ),
        key=lambda f: (
            f.id,
            f.source_location.path if f.source_location else "",
            f.description,
        ),
    )
    return ContractDiff(changes=ordered, findings=tuple(findings))


def _diff_operation(
    old_op: OpenApiOperation,
    new_op: OpenApiOperation,
    old_params: dict[tuple[str, str], OpenApiParameter],
    new_params: dict[tuple[str, str], OpenApiParameter],
    old_bodies: dict[tuple[str, str], OpenApiRequestBody],
    new_bodies: dict[tuple[str, str], OpenApiRequestBody],
    old_responses: dict[tuple[str, str], OpenApiResponse],
    new_responses: dict[tuple[str, str], OpenApiResponse],
    old_schemas: dict[str, Any],
    new_schemas: dict[str, Any],
    old_reqs: dict[tuple[str, str], list[frozenset[str]]],
    new_reqs: dict[tuple[str, str], list[frozenset[str]]],
) -> list[ContractChange]:
    out: list[ContractChange] = []
    subject = old_op.identity

    def op_params(
        model_params: dict[tuple[str, str], OpenApiParameter], op: OpenApiOperation
    ) -> dict[tuple[str, str], OpenApiParameter]:
        result: dict[tuple[str, str], OpenApiParameter] = {}
        for ptr in op.parameter_pointers:
            p = model_params.get((op.location.path, ptr))
            if p is not None and p.name is not None and p.location_in is not None:
                result[(p.name, p.location_in)] = p
        return result

    o_params, n_params = op_params(old_params, old_op), op_params(new_params, new_op)
    for key in sorted(set(o_params) - set(n_params)):
        name, where = key
        out.append(
            ContractChange(
                kind="param_removed",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.REQUEST,
                subject=subject,
                path=f"{old_op.path}#{where}/{name}",
                detail=f"{subject}: parameter {name!r} ({where}) removed",
                location=old_op.location,
            )
        )
    for key in sorted(set(n_params) - set(o_params)):
        name, where = key
        p = n_params[key]
        out.append(
            ContractChange(
                kind="param_added_required" if p.required else "param_added_optional",
                classification=(
                    CompatibilityClass.BREAKING
                    if p.required
                    else CompatibilityClass.POTENTIALLY_BREAKING
                ),
                side=ChangeSide.REQUEST,
                subject=subject,
                path=f"{old_op.path}#{where}/{name}",
                detail=(
                    f"{subject}: {'required' if p.required else 'optional'} parameter "
                    f"{name!r} ({where}) added"
                ),
                location=new_op.location,
            )
        )
    for key in sorted(set(o_params) & set(n_params)):
        o, n = o_params[key], n_params[key]
        if not o.required and n.required:
            out.append(
                ContractChange(
                    kind="param_added_required",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.REQUEST,
                    subject=subject,
                    path=f"{old_op.path}#{key[1]}/{key[0]}",
                    detail=f"{subject}: parameter {key[0]!r} ({key[1]}) became required",
                    location=new_op.location,
                )
            )
        o_schema = o.schema if isinstance(o.schema, dict) else None
        n_schema = n.schema if isinstance(n.schema, dict) else None
        if o_schema is not None or n_schema is not None:
            differ = _SchemaDiff(new_schemas, subject, ChangeSide.REQUEST, new_op.location)
            differ.diff(o_schema, n_schema, f"param:{key[0]}")
            out.extend(differ.out)

    # request body
    o_body = (
        old_bodies.get((old_op.location.path, old_op.request_body_pointer))
        if old_op.request_body_pointer
        else None
    )
    n_body = (
        new_bodies.get((new_op.location.path, new_op.request_body_pointer))
        if new_op.request_body_pointer
        else None
    )
    if o_body is not None and n_body is None:
        out.append(
            ContractChange(
                kind="param_removed",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.REQUEST,
                subject=subject,
                path=f"{old_op.path}#requestBody",
                detail=f"{subject}: request body removed",
                location=old_op.location,
            )
        )
    elif o_body is None and n_body is not None:
        out.append(
            ContractChange(
                kind="request_body_added",
                classification=CompatibilityClass.POTENTIALLY_BREAKING,
                side=ChangeSide.REQUEST,
                subject=subject,
                path=f"{old_op.path}#requestBody",
                detail=f"{subject}: request body added",
                location=new_op.location,
            )
        )
    elif o_body is not None and n_body is not None:
        for ctype in sorted(set(o_body.content_types) - set(n_body.content_types)):
            out.append(
                ContractChange(
                    kind="content_type_removed",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.REQUEST,
                    subject=subject,
                    path=f"{old_op.path}#requestBody/{ctype}",
                    detail=f"{subject}: request content-type {ctype} removed",
                    location=new_op.location,
                )
            )
        _diff_schemas_by_shape(
            o_body.schema_shapes,
            n_body.schema_shapes,
            old_schemas,
            new_schemas,
            ChangeSide.REQUEST,
            subject,
            "requestBody",
            new_op.location,
            out,
        )

    # responses
    o_resp = [
        old_responses[(old_op.location.path, p)]
        for p in old_op.response_pointers
        if (old_op.location.path, p) in old_responses
    ]
    n_resp = [
        new_responses[(new_op.location.path, p)]
        for p in new_op.response_pointers
        if (new_op.location.path, p) in new_responses
    ]
    o_by_status = {r.status: r for r in o_resp if r.status}
    n_by_status = {r.status: r for r in n_resp if r.status}
    for status in sorted(set(o_by_status) - set(n_by_status)):
        out.append(
            ContractChange(
                kind="status_removed",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.RESPONSE,
                subject=subject,
                path=f"{old_op.path}#responses/{status}",
                detail=f"{subject}: response status {status} removed",
                location=old_op.location,
            )
        )
    for status in sorted(set(o_by_status) & set(n_by_status)):
        o_r, n_r = o_by_status[status], n_by_status[status]
        for ctype in sorted(set(o_r.content_types) - set(n_r.content_types)):
            out.append(
                ContractChange(
                    kind="content_type_removed",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=subject,
                    path=f"{old_op.path}#responses/{status}/{ctype}",
                    detail=f"{subject}: response {status} content-type {ctype} removed",
                    location=new_op.location,
                )
            )
        _diff_schemas_by_shape(
            o_r.schema_shapes,
            n_r.schema_shapes,
            old_schemas,
            new_schemas,
            ChangeSide.RESPONSE,
            subject,
            f"response[{status}]",
            new_op.location,
            out,
        )

    # auth (OR alternatives, op-level overrides root including `security: []`)
    o_auth = _effective_security(old_reqs, old_op)
    n_auth = _effective_security(new_reqs, new_op)
    if o_auth != n_auth:
        still_allowed = all(
            any(new_alt <= old_alt for new_alt in n_auth) for old_alt in o_auth
        )
        expanded = any(
            not any(new_alt <= old_alt for new_alt in n_auth) for old_alt in o_auth
        ) or any(
            not any(old_alt <= new_alt for old_alt in o_auth) for new_alt in n_auth
        )
        if not still_allowed:
            out.append(
                ContractChange(
                    kind="auth_tightened",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.META,
                    subject=subject,
                    path=f"{old_op.path}#security",
                    detail=(
                        f"{subject}: security requirement "
                        f"{sorted(map(sorted, o_auth))} -> {sorted(map(sorted, n_auth))}"
                    ),
                    location=new_op.location,
                )
            )
        elif expanded:
            out.append(
                ContractChange(
                    kind="auth_loosened",
                    classification=CompatibilityClass.NON_BREAKING,
                    side=ChangeSide.META,
                    subject=subject,
                    path=f"{old_op.path}#security",
                    detail=(
                        f"{subject}: security requirement loosened "
                        f"{sorted(map(sorted, o_auth))} -> {sorted(map(sorted, n_auth))}"
                    ),
                    location=new_op.location,
                )
            )
    return out
