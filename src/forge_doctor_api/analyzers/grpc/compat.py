"""Proto compatibility diff (§26) via unified compat classes (§121).

Rules: removed field, field-number reuse, incompatible field-type change,
removed enum values, removed method, unary<->streaming change,
package/service rename. Field-number bookkeeping powers GRPC003/004.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.grpc.model import (
    GrpcProjectModel,
    ProtoField,
    ProtoMessage,
)
from forge_doctor_api.checks.compat.catalog import ChangeSide, CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractChange

# wire-compatible scalar families; anything else is a wire-format break
_WIRE_GROUPS = [
    {"int32", "int64", "uint32", "uint64", "sint32", "sint64", "bool",
     "enum"},
    {"sint32", "sint64"},
    {"fixed32", "sfixed32", "float"},
    {"fixed64", "sfixed64", "double"},
    {"string"},
    {"bytes"},
]


def _wire_group(t: str) -> int | None:
    for i, group in enumerate(_WIRE_GROUPS):
        if t in group:
            return i
    return None


def _subject(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def diff_proto_models(
    old: GrpcProjectModel, new: GrpcProjectModel
) -> tuple[ContractChange, ...]:
    changes: list[ContractChange] = []

    # package / service rename
    old_svcs = {(s.package, s.name): s for s in old.services}
    new_svcs = {(s.package, s.name): s for s in new.services}
    for key in sorted(set(old_svcs) - set(new_svcs)):
        s = old_svcs[key]
        changes.append(
            ContractChange(
                kind="GRPC_RENAME",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.RESPONSE,
                subject=_subject("grpc_service", f"{s.package}.{s.name}"),
                path=f"service:{s.package}.{s.name}",
                detail=f"package/service removed or renamed: {s.package}.{s.name}",
                before=f"{s.package}.{s.name}",
                location=s.location,
            )
        )
    for key in sorted(set(old_svcs) & set(new_svcs)):
        os_, ns = old_svcs[key], new_svcs[key]
        old_m = {m.name: m for m in os_.methods}
        new_m = {m.name: m for m in ns.methods}
        for name in sorted(set(old_m) - set(new_m)):
            changes.append(
                ContractChange(
                    kind="GRPC_METHOD_REMOVED",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("grpc_service", key[0] + "." + key[1]),
                    path=f"method:{key[0]}.{key[1]}/{name}",
                    detail=f"method removed: {name}",
                    before=name,
                    location=old_m[name].location,
                )
            )
        for name in sorted(set(old_m) & set(new_m)):
            ometh, nmeth = old_m[name], new_m[name]
            if ometh.streaming is not nmeth.streaming:
                changes.append(
                    ContractChange(
                        kind="GRPC006",
                        classification=CompatibilityClass.BREAKING,
                        side=ChangeSide.RESPONSE,
                        subject=_subject("grpc_method", f"{key[0]}.{key[1]}/{name}"),
                        path=f"method:{key[0]}.{key[1]}/{name}",
                        detail=(
                            f"streaming mode changed: {ometh.streaming.value} -> "
                            f"{nmeth.streaming.value}"
                        ),
                        before=ometh.streaming.value,
                        after=nmeth.streaming.value,
                        location=nmeth.location,
                    )
                )

    # messages: field removal / number reuse / type change
    old_msgs = {m.name: m for m in old.messages}
    new_msgs = {m.name: m for m in new.messages}
    for name in sorted(set(old_msgs) & set(new_msgs)):
        om, nm = old_msgs[name], new_msgs[name]
        changes.extend(_diff_message(name, om, nm))
    for name in sorted(set(old_msgs) - set(new_msgs)):
        om = old_msgs[name]
        changes.append(
            ContractChange(
                kind="GRPC_FIELD_REMOVED",
                classification=CompatibilityClass.BREAKING,
                side=ChangeSide.RESPONSE,
                subject=_subject("proto_message", name),
                path=f"message:{name}",
                detail=f"message removed: {name}",
                location=om.location,
            )
        )

    # enums
    old_enums = {e.name: e for e in old.enums}
    new_enums = {e.name: e for e in new.enums}
    for name in sorted(set(old_enums) & set(new_enums)):
        removed = sorted(set(old_enums[name].values) - set(new_enums[name].values))
        for v in removed:
            changes.append(
                ContractChange(
                    kind="GRPC_ENUM_REMOVED",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("proto_enum", name),
                    path=f"enum:{name}.{v}",
                    detail=f"enum value removed: {name}.{v}",
                    before=v,
                    location=old_enums[name].location,
                )
            )
        # spec 087 — renumbering: same value name, different wire number
        shared = set(old_enums[name].values) & set(new_enums[name].values)
        for v in sorted(shared):
            o_num, n_num = (
                old_enums[name].values[v], new_enums[name].values[v])
            if o_num != n_num:
                changes.append(
                    ContractChange(
                        kind="GRPC008",
                        classification=CompatibilityClass.BREAKING,
                        side=ChangeSide.RESPONSE,
                        subject=_subject("proto_enum", name),
                        path=f"enum:{name}.{v}",
                        detail=(
                            f"enum value renumbered: {name}.{v} "
                            f"{o_num} -> {n_num}"),
                        before=str(o_num),
                        after=str(n_num),
                        location=new_enums[name].location,
                    )
                )
    return tuple(changes)


def _diff_message(
    name: str, old: ProtoMessage, new: ProtoMessage
) -> list[ContractChange]:
    changes: list[ContractChange] = []
    old_by_num = {f.number: f for f in old.fields}
    new_by_num = {f.number: f for f in new.fields}
    old_by_name = {f.name: f for f in old.fields}
    new_by_name = {f.name: f for f in new.fields}

    # removed fields
    for num in sorted(set(old_by_num) - set(new_by_num)):
        f = old_by_num[num]
        reserved = num in new.reserved_numbers
        changes.append(
            ContractChange(
                kind="GRPC003",
                classification=(
                    CompatibilityClass.BREAKING
                    if not reserved
                    else CompatibilityClass.POTENTIALLY_BREAKING
                ),
                side=ChangeSide.RESPONSE,
                subject=_subject("proto_message", name),
                path=f"field:{name}.{f.name}",
                detail=(
                    f"field removed {'without' if not reserved else 'with'} "
                    f"`reserved`: {name}.{f.name} = {num}"
                ),
                before=f"{f.name} = {num}",
                location=f.location,
            )
        )

    # number reuse: same number, different field name (type-agnostic)
    for num in sorted(set(old_by_num) & set(new_by_num)):
        of, nf = old_by_num[num], new_by_num[num]
        if of.name != nf.name:
            changes.append(
                ContractChange(
                    kind="GRPC004",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("proto_message", name),
                    path=f"field:{name}#{num}",
                    detail=(
                        f"field number {num} reused: {of.name}({of.type}) -> "
                        f"{nf.name}({nf.type})"
                    ),
                    before=f"{of.name}:{of.type}",
                    after=f"{nf.name}:{nf.type}",
                    location=nf.location,
                )
            )

    # oneof membership: a field entering/leaving a oneof changes
    # exclusivity semantics even when number+type are stable
    for fname in sorted(set(old_by_name) & set(new_by_name)):
        of, nf = old_by_name[fname], new_by_name[fname]
        if (of.oneof or None) != (nf.oneof or None):
            changes.append(
                ContractChange(
                    kind="GRPC009",
                    classification=CompatibilityClass.BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("proto_message", name),
                    path=f"field:{name}.{fname}",
                    detail=(
                        f"oneof membership changed: {name}.{fname} "
                        f"{of.oneof or '(none)'} -> {nf.oneof or '(none)'}"),
                    before=of.oneof,
                    after=nf.oneof,
                    location=nf.location,
                )
            )
    # oneof member added to a surviving oneof — decoders matching
    # variants exhaustively may not handle the new member
    for oneof in sorted(set(old.oneofs) & set(new.oneofs)):
        old_members = {f.name for f in old.fields if f.oneof == oneof}
        new_members = {f.name for f in new.fields if f.oneof == oneof}
        for fname in sorted(new_members - old_members):
            changes.append(
                ContractChange(
                    kind="GRPC009",
                    classification=CompatibilityClass.POTENTIALLY_BREAKING,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("proto_message", name),
                    path=f"oneof:{name}.{oneof}.{fname}",
                    detail=(
                        f"oneof member added: {oneof} gains {fname}; "
                        "exhaustive decoders may not handle it"),
                    before=None,
                    after=fname,
                    location=new.location,
                )
            )

    # same-name field type changes (number kept, name kept)
    for fname in sorted(set(old_by_name) & set(new_by_name)):
        of, nf = old_by_name[fname], new_by_name[fname]
        if of.number == nf.number and _type_changed(of, nf):
            og, ng = _wire_group(of.type), _wire_group(nf.type)
            cls = (
                CompatibilityClass.POTENTIALLY_BREAKING
                if og is not None and og == ng
                else CompatibilityClass.BREAKING
            )
            changes.append(
                ContractChange(
                    kind="GRPC_TYPE_CHANGED",
                    classification=cls,
                    side=ChangeSide.RESPONSE,
                    subject=_subject("proto_message", name),
                    path=f"field:{name}.{fname}",
                    detail=(
                        f"field type changed: {name}.{fname} {of.type} -> "
                        f"{nf.type} (wire group {'same' if og == ng else 'diff'})"
                    ),
                    before=of.type,
                    after=nf.type,
                    location=nf.location,
                )
            )
    return changes


def _type_changed(a: ProtoField, b: ProtoField) -> bool:
    return a.type != b.type or (a.label or "") != (b.label or "")
