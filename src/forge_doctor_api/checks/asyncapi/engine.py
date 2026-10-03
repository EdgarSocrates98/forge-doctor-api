"""ASYNC001-008 check engine (§21, spec 011).

Schema drift (ASYNC003) and message evolution (ASYNC006) reuse the unified
schema diff from `checks.compat` (§121) — no parallel compatibility rules.
Candidate checks (004/005/007/008) attach `UnknownFact`s and never assert
policy violations the document cannot prove.
"""

from __future__ import annotations

import re
from collections import defaultdict

from forge_doctor_api.analyzers.asyncapi.model import (
    AsyncAction,
    AsyncApiChannel,
    AsyncApiMessage,
    AsyncApiOperation,
    AsyncApiProjectModel,
)
from forge_doctor_api.checks.asyncapi.catalog import BY_ID, AsyncCheckSpec
from forge_doctor_api.checks.compat import ContractChange, diff_schema_content
from forge_doctor_api.checks.compat.catalog import ChangeSide
from forge_doctor_api.core.models import (
    Evidence,
    Finding,
    SourceLocation,
    UnknownFact,
    entity_id,
)

_RETRY = re.compile(r"retr(y|ies)|maxretries|redelivery", re.I)
_DLQ = re.compile(r"dlq|dead.?letter", re.I)
_ORDER = re.compile(r"partition|ordering|orderingkey|message.?key|\bkey\b", re.I)
_DELIVERY = re.compile(r"acks|qos|delivery|confirm|persist|commit", re.I)


def _finding(
    spec: AsyncCheckSpec,
    description: str,
    location: SourceLocation,
    entities: tuple[str, ...] = (),
    unknowns: tuple[UnknownFact, ...] = (),
) -> Finding:
    return Finding(
        id=spec.id,
        title=spec.title,
        description=description,
        severity=spec.severity,
        confidence=spec.confidence,
        evidence_kind=spec.evidence_kind,
        evidence=(
            Evidence(
                kind=spec.evidence_kind,
                source=location.path,
                summary=description,
                line=location.line,
            ),
        ),
        entity_ids=entities,
        source_location=location,
        unknowns=unknowns,
    )


def _channel_entity(channel: AsyncApiChannel) -> str:
    return entity_id("async_channel", channel.location.path, channel.name)


def _message_entity(message: AsyncApiMessage) -> str:
    return entity_id(
        "message", message.location.path, message.name or message.pointer
    )


def _op_entity(op: AsyncApiOperation) -> str:
    return entity_id("operation", "asyncapi", f"{op.action}:{op.name}")


def _payloads(
    messages: list[AsyncApiMessage], schemas: dict[str, object]
) -> list[object]:
    """Resolved payload contents for a set of messages (refs followed once)."""
    out: list[object] = []
    for message in messages:
        content = message.payload_content
        if isinstance(content, dict) and isinstance(content.get("$ref"), str):
            resolved = schemas.get(content["$ref"].rsplit("/", 1)[-1])
            content = resolved if resolved is not None else content
        if content is None and message.payload_ref:
            content = schemas.get(message.payload_ref)
        if content is not None:
            out.append(content)
    return out


def run_async_checks(model: AsyncApiProjectModel) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    schemas = {s.name: s.content for s in model.schemas}
    messages_by_ptr = {m.pointer: m for m in model.messages}
    ops_by_channel: dict[str, list[AsyncApiOperation]] = defaultdict(list)
    for op in model.operations:
        if op.channel_pointer:
            ops_by_channel[op.channel_pointer].append(op)

    def channel_messages(channel: AsyncApiChannel) -> list[AsyncApiMessage]:
        ptrs = list(channel.message_pointers)
        for op in ops_by_channel.get(channel.pointer, []):
            ptrs.extend(op.message_pointers)
        return [messages_by_ptr[p] for p in ptrs if p in messages_by_ptr]

    # ASYNC001 channel without message schema
    for channel in model.channels:
        msgs = channel_messages(channel)
        if not [p for p in _payloads(msgs, schemas)]:
            findings.append(
                _finding(
                    BY_ID["ASYNC001"],
                    f"channel {channel.name!r} has no resolvable message payload schema",
                    channel.location,
                    (_channel_entity(channel),),
                )
            )

    # ASYNC002 missing correlation id
    for message in model.messages:
        if message.correlation_id_location is None:
            findings.append(
                _finding(
                    BY_ID["ASYNC002"],
                    f"message {message.name or message.pointer!r} has no correlationId",
                    message.location,
                    (_message_entity(message),),
                )
            )

    # ASYNC003 producer/consumer schema drift (unified schema diff, §121-123)
    for channel in model.channels:
        ops = ops_by_channel.get(channel.pointer, [])
        send_msgs = [
            messages_by_ptr[p]
            for op in ops
            if op.action is AsyncAction.SEND
            for p in op.message_pointers
            if p in messages_by_ptr
        ]
        recv_msgs = [
            messages_by_ptr[p]
            for op in ops
            if op.action is AsyncAction.RECEIVE
            for p in op.message_pointers
            if p in messages_by_ptr
        ]
        if not send_msgs or not recv_msgs:
            continue
        changes: list[ContractChange] = []
        for send in _payloads(send_msgs, schemas):
            for recv in _payloads(recv_msgs, schemas):
                changes.extend(
                    diff_schema_content(
                        send,
                        recv,
                        side=ChangeSide.RESPONSE,
                        subject=_op_entity(ops[0]),
                        path=f"channel:{channel.name}",
                        schemas=schemas,
                        location=channel.location,
                    )
                )
        if changes:
            detail = "; ".join(sorted({c.detail for c in changes}))
            findings.append(
                _finding(
                    BY_ID["ASYNC003"],
                    f"channel {channel.name!r}: producer/consumer payload drift — {detail}",
                    channel.location,
                    (_channel_entity(channel),),
                )
            )

    # ASYNC004 retry without DLQ (channels and operations)
    for channel in model.channels:
        markers = " ".join(channel.markers).lower()
        if _RETRY.search(markers) and not _DLQ.search(markers):
            findings.append(
                _finding(
                    BY_ID["ASYNC004"],
                    f"channel {channel.name!r} shows retry evidence without "
                    "DLQ/dead-letter markers",
                    channel.location,
                    (_channel_entity(channel),),
                    (
                        UnknownFact(
                            subject=f"channel:{channel.name}",
                            missing="dead-letter queue evidence",
                            resolution="retry policy may be configured in the broker, "
                            "not the contract",
                        ),
                    ),
                )
            )
        if "kafka" in channel.bindings and not _ORDER.search(markers):
            findings.append(
                _finding(
                    BY_ID["ASYNC005"],
                    f"channel {channel.name!r} is kafka-bound without partitioning/"
                    "ordering evidence",
                    channel.location,
                    (_channel_entity(channel),),
                    (
                        UnknownFact(
                            subject=f"channel:{channel.name}",
                            missing="ordering/partitioning declaration",
                            resolution="ordering may be enforced by message keys outside "
                            "the document",
                        ),
                    ),
                )
            )
    for op in model.operations:
        markers = " ".join(op.markers).lower()
        if _RETRY.search(markers) and not _DLQ.search(markers):
            findings.append(
                _finding(
                    BY_ID["ASYNC004"],
                    f"operation {op.name!r} shows retry evidence without "
                    "DLQ/dead-letter markers",
                    op.location,
                    (_op_entity(op),),
                    (
                        UnknownFact(
                            subject=f"operation:{op.name}",
                            missing="dead-letter queue evidence",
                            resolution="retry policy may be configured in the broker, "
                            "not the contract",
                        ),
                    ),
                )
            )
        if not _DELIVERY.search(markers) and not op.bindings:
            findings.append(
                _finding(
                    BY_ID["ASYNC008"],
                    f"operation {op.name!r} has no delivery-semantics evidence "
                    "(acks/qos/delivery-mode bindings)",
                    op.location,
                    (_op_entity(op),),
                    (
                        UnknownFact(
                            subject=f"operation:{op.name}",
                            missing="delivery guarantee evidence",
                            resolution="delivery semantics may come from the broker config",
                        ),
                    ),
                )
            )

    # ASYNC006 incompatible message evolution: same name, different payloads
    by_name: dict[str, list[AsyncApiMessage]] = defaultdict(list)
    for message in model.messages:
        if message.name:
            by_name[message.name].append(message)
    for name in sorted(by_name):
        group = by_name[name]
        if len(group) < 2:
            continue
        payloads = _payloads(group, schemas)
        if len(payloads) < 2:
            continue
        drift: list[ContractChange] = []
        first, *rest = payloads
        for other in rest:
            drift.extend(
                diff_schema_content(
                    first,
                    other,
                    side=ChangeSide.RESPONSE,
                    subject=_message_entity(group[0]),
                    path=f"message:{name}",
                    schemas=schemas,
                    location=group[0].location,
                )
            )
        if drift:
            findings.append(
                _finding(
                    BY_ID["ASYNC006"],
                    f"message {name!r} has {len(group)} incompatible payload variants: "
                    + "; ".join(sorted({c.detail for c in drift})),
                    group[0].location,
                    tuple(_message_entity(m) for m in group),
                )
            )

    # ASYNC007 missing consumer ownership
    for channel in model.channels:
        ops = ops_by_channel.get(channel.pointer, [])
        has_send = any(o.action is AsyncAction.SEND for o in ops)
        has_recv = any(o.action is AsyncAction.RECEIVE for o in ops)
        if has_send and not has_recv:
            findings.append(
                _finding(
                    BY_ID["ASYNC007"],
                    f"channel {channel.name!r} is produced to but declares no consumer",
                    channel.location,
                    (_channel_entity(channel),),
                    (
                        UnknownFact(
                            subject=f"channel:{channel.name}",
                            missing="consumer declaration",
                            resolution="consumers may exist in other services not "
                            "described by this document",
                        ),
                    ),
                )
            )

    return tuple(
        sorted(
            findings,
            key=lambda f: (
                f.id,
                f.source_location.path if f.source_location else "",
                f.source_location.line if f.source_location else 0,
                f.description,
            ),
        )
    )
