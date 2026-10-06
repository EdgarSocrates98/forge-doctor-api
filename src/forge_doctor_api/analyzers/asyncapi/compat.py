"""AsyncAPI compat diff (spec 087, §20) via unified compat classes (§121).

Covers the semantic axes a brokered contract can break on: channel
removal, operation action flips (send<->receive), message payload-shape
drift, correlation-id relocation, and binding set changes. Every change
carries its `SourceLocation`; nothing is inferred — a payload shape that
cannot be decomposed classifies POTENTIALLY, never silently BREAKING.
"""

from __future__ import annotations

from typing import Any

from forge_doctor_api.analyzers.asyncapi.model import (
    AsyncApiMessage,
    AsyncApiProjectModel,
)
from forge_doctor_api.checks.compat.catalog import ChangeSide, CompatibilityClass
from forge_doctor_api.checks.compat.engine import (
    ContractChange,
    diff_schema_content,
)


def _subject(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def _payload_content(
    message: AsyncApiMessage, schemas: dict[str, Any]
) -> Any:
    """Resolve a message payload to its schema content, following one
    local `$ref`/`payload_ref` hop — same rule as the check engine."""
    content: Any = message.payload_content
    if isinstance(content, dict) and isinstance(content.get("$ref"), str):
        resolved = schemas.get(content["$ref"].rsplit("/", 1)[-1])
        content = resolved if resolved is not None else content
    if content is None and message.payload_ref:
        content = schemas.get(message.payload_ref)
    return content


def diff_asyncapi_models(
    old: AsyncApiProjectModel, new: AsyncApiProjectModel
) -> tuple[ContractChange, ...]:
    """Classify breaking changes between two AsyncAPI project models."""
    changes: list[ContractChange] = []

    # channels: keyed by declared name (2.x key) — a renamed channel is a
    # removal plus an addition, never a fuzzy match.
    old_ch = {c.name: c for c in old.channels}
    new_ch = {c.name: c for c in new.channels}
    for name in sorted(set(old_ch) - set(new_ch)):
        changes.append(
            ContractChange(
                kind="ASYNC009",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.RESPONSE,
                subject=_subject("async_channel", name),
                path=f"channel:{name}",
                detail=f"channel removed: {name}",
                before=name,
                location=old_ch[name].location,
            )
        )
    for name in sorted(set(new_ch) - set(old_ch)):
        changes.append(
            ContractChange(
                kind="ASYNC010",
                classification=CompatibilityClass.POTENTIALLY_BREAKING,
                side=ChangeSide.RESPONSE,
                subject=_subject("async_channel", name),
                path=f"channel:{name}",
                detail=f"channel added: {name}",
                after=name,
                location=new_ch[name].location,
            )
        )
    for name in sorted(set(old_ch) & set(new_ch)):
        oc, nc = old_ch[name], new_ch[name]
        if oc.bindings != nc.bindings:
            changes.append(
                ContractChange(
                    kind="ASYNC017",
                    classification=CompatibilityClass.POTENTIALLY_BREAKING,
                    side=ChangeSide.META,
                    subject=_subject("async_channel", name),
                    path=f"channel:{name}.bindings",
                    detail=(
                        f"channel {name} bindings changed "
                        f"{sorted(oc.bindings)} -> {sorted(nc.bindings)}"),
                    before=",".join(sorted(oc.bindings)),
                    after=",".join(sorted(nc.bindings)),
                    location=nc.location,
                )
            )

    # operations: keyed by declared name; action flip is a semantic break
    old_ops = {o.name: o for o in old.operations}
    new_ops = {o.name: o for o in new.operations}
    for name in sorted(set(old_ops) - set(new_ops)):
        changes.append(
            ContractChange(
                kind="ASYNC011",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.RESPONSE,
                subject=_subject("async_operation", name),
                path=f"operation:{name}",
                detail=f"operation removed: {name}",
                before=name,
                location=old_ops[name].location,
            )
        )
    for name in sorted(set(old_ops) & set(new_ops)):
        oo, no = old_ops[name], new_ops[name]
        if oo.action is not no.action:
            changes.append(
                ContractChange(
                    kind="ASYNC012",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.META,
                    subject=_subject("async_operation", name),
                    path=f"operation:{name}.action",
                    detail=(
                        f"operation {name} action flipped "
                        f"{oo.action.value} -> {no.action.value}"),
                    before=oo.action.value,
                    after=no.action.value,
                    location=no.location,
                )
            )
        if oo.bindings != no.bindings:
            changes.append(
                ContractChange(
                    kind="ASYNC017",
                    classification=CompatibilityClass.POTENTIALLY_BREAKING,
                    side=ChangeSide.META,
                    subject=_subject("async_operation", name),
                    path=f"operation:{name}.bindings",
                    detail=(
                        f"operation {name} bindings changed "
                        f"{sorted(oo.bindings)} -> {sorted(no.bindings)}"),
                    before=",".join(sorted(oo.bindings)),
                    after=",".join(sorted(no.bindings)),
                    location=no.location,
                )
            )

    # messages: keyed by declared name (fall back to pointer identity)
    def _key(m: AsyncApiMessage) -> str:
        return m.name or m.pointer

    old_msg = {_key(m): m for m in old.messages}
    new_msg = {_key(m): m for m in new.messages}
    for name in sorted(set(old_msg) - set(new_msg)):
        changes.append(
            ContractChange(
                kind="ASYNC014",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.RESPONSE,
                subject=_subject("message", name),
                path=f"message:{name}",
                detail=f"message removed: {name}",
                before=name,
                location=old_msg[name].location,
            )
        )
    for name in sorted(set(old_msg) & set(new_msg)):
        om, nm = old_msg[name], new_msg[name]
        if om.correlation_id_location != nm.correlation_id_location:
            changes.append(
                ContractChange(
                    kind="ASYNC013",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.REQUEST,
                    subject=_subject("message", name),
                    path=f"message:{name}.correlationId",
                    detail=(
                        f"correlation-id location changed: {name} "
                        f"{om.correlation_id_location!r} -> "
                        f"{nm.correlation_id_location!r}"),
                    before=om.correlation_id_location,
                    after=nm.correlation_id_location,
                    location=nm.location,
                )
            )
        # payload: resolve refs into component content and run the
        # unified schema diff — property-level drift inside a stable ref
        # must surface, not just ref-pointer moves (spec 087).
        schemas = {s.name: s.content for s in new.schemas}
        o_content = _payload_content(
            om, {s.name: s.content for s in old.schemas})
        n_content = _payload_content(nm, schemas)
        if o_content is not None and n_content is not None:
            drift = diff_schema_content(
                o_content, n_content,
                side=ChangeSide.RESPONSE,
                subject=_subject("message", name),
                path=f"message:{name}.payload",
                schemas=schemas,
                location=nm.location,
            )
            if drift:
                detail = "; ".join(sorted({d.detail for d in drift}))[:300]
                unknown = any(
                    d.classification is CompatibilityClass.UNKNOWN
                    for d in drift)
                changes.append(
                    ContractChange(
                        kind="ASYNC015",
                        classification=(
                            CompatibilityClass.POTENTIALLY_BREAKING
                            if unknown
                            else CompatibilityClass.BREAKING),
                        side=ChangeSide.RESPONSE,
                        subject=_subject("message", name),
                        path=f"message:{name}.payload",
                        detail=f"message payload schema changed: {name} — "
                        f"{detail}",
                        before=None, after=None,
                        location=nm.location,
                    )
                )
        elif (om.payload_shape or None) != (nm.payload_shape or None):
            # content unresolvable on a side — fall back to shape identity
            changes.append(
                ContractChange(
                    kind="ASYNC015",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("message", name),
                    path=f"message:{name}.payload",
                    detail=(
                        f"message payload shape changed: {name} "
                        f"{om.payload_shape!r} -> {nm.payload_shape!r}"),
                    before=om.payload_shape,
                    after=nm.payload_shape,
                    location=nm.location,
                )
            )
        if (om.content_type or None) != (nm.content_type or None):
            changes.append(
                ContractChange(
                    kind="ASYNC016",
                    classification=CompatibilityClass.POTENTIALLY_BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("message", name),
                    path=f"message:{name}.contentType",
                    detail=(
                        f"message content-type changed: {name} "
                        f"{om.content_type!r} -> {nm.content_type!r}"),
                    before=om.content_type,
                    after=nm.content_type,
                    location=nm.location,
                )
            )
        if om.bindings != nm.bindings:
            changes.append(
                ContractChange(
                    kind="ASYNC017",
                    classification=CompatibilityClass.POTENTIALLY_BREAKING,
                    side=ChangeSide.META,
                    subject=_subject("message", name),
                    path=f"message:{name}.bindings",
                    detail=(
                        f"message {name} bindings changed "
                        f"{sorted(om.bindings)} -> {sorted(nm.bindings)}"),
                    before=",".join(sorted(om.bindings)),
                    after=",".join(sorted(nm.bindings)),
                    location=nm.location,
                )
            )
    return tuple(sorted(
        changes, key=lambda c: (c.kind, c.subject, c.path, c.detail)))
