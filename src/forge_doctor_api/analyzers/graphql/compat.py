"""GraphQL schema evolution - GQL002-005 routed through the unified
`ContractChange`/`CompatibilityClass`/`ChangeSide` machinery (§121-123).

Direction polarity mirrors §123: output positions (object fields) break
readers; input positions (arguments, input-object fields) break writers.
"""

from __future__ import annotations

from forge_doctor_api.analyzers.graphql.model import (
    GraphQLProjectModel,
    GraphQLTypeKind,
)
from forge_doctor_api.checks.compat.catalog import ChangeSide, CompatibilityClass
from forge_doctor_api.checks.compat.engine import ContractChange


def _subject(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def diff_graphql_schemas(
    old: GraphQLProjectModel, new: GraphQLProjectModel
) -> tuple[ContractChange, ...]:
    """Classify breaking changes between two GraphQL schema models."""
    changes: list[ContractChange] = []
    old_types = {t.name: t for t in old.types}
    new_types = {t.name: t for t in new.types}

    for name in sorted(old_types):
        ot = old_types[name]
        nt = new_types.get(name)
        if nt is None:
            continue  # removed types surface via field diffs on surviving refs

        if ot.kind is GraphQLTypeKind.ENUM and nt.kind is GraphQLTypeKind.ENUM:
            removed = sorted(set(ot.enum_values) - set(nt.enum_values))
            for v in removed:
                changes.append(
                    ContractChange(
                        kind="GQL005",
                        classification=CompatibilityClass.BREAKING,
                        side=ChangeSide.RESPONSE,
                        subject=_subject("enum", name),
                        path=f"enum:{name}.{v}",
                        detail=f"enum value removed: {name}.{v}",
                        before=v,
                        after=None,
                        location=ot.location,
                    )
                )
            continue

        if ot.kind not in {
            GraphQLTypeKind.OBJECT,
            GraphQLTypeKind.INTERFACE,
            GraphQLTypeKind.INPUT_OBJECT,
        } or nt.kind is not ot.kind:
            continue

        old_fields = {f.name: f for f in ot.fields}
        new_fields = {f.name: f for f in nt.fields}
        side = (
            ChangeSide.REQUEST
            if ot.kind is GraphQLTypeKind.INPUT_OBJECT
            else ChangeSide.RESPONSE
        )
        label = "input field" if side is ChangeSide.REQUEST else "field"
        for fname in sorted(set(old_fields) - set(new_fields)):
            changes.append(
                ContractChange(
                    kind="GQL002",
                    classification=CompatibilityClass.BREAKING,
                    side=side,
                    subject=_subject("graphql_type", name),
                    path=f"field:{name}.{fname}",
                    detail=f"{label} removed: {name}.{fname}",
                    before=fname,
                    after=None,
                    location=old_fields[fname].location,
                )
            )
        for fname in sorted(set(old_fields) & set(new_fields)):
            of, nf = old_fields[fname], new_fields[fname]
            # nullable -> non-null: breaking for the side that reads/writes it
            if of.type.nullable and not nf.type.nullable:
                changes.append(
                    ContractChange(
                        kind="GQL004",
                        classification=CompatibilityClass.BREAKING,
                        side=side,
                        subject=_subject("graphql_type", name),
                        path=f"field:{name}.{fname}",
                        detail=(
                            f"{label} nullable->non-null: {name}.{fname} "
                            f"({side.value} position)"
                        ),
                        before="nullable",
                        after="non-null",
                        location=nf.location,
                    )
                )
            if ot.kind is GraphQLTypeKind.INPUT_OBJECT:
                continue  # input objects have no nested arguments
            old_args = {a.name: a for a in of.arguments}
            new_args = {a.name: a for a in nf.arguments}
            for aname in sorted(set(new_args) - set(old_args)):
                na = new_args[aname]
                if na.required:
                    changes.append(
                        ContractChange(
                            kind="GQL003",
                            classification=CompatibilityClass.BREAKING,
                            side=ChangeSide.REQUEST,
                            subject=_subject("graphql_field", f"{name}.{fname}"),
                            path=f"argument:{name}.{fname}({aname})",
                            detail=(
                                f"required argument added: {name}.{fname}({aname}: "
                                f"{na.type.name}!)"
                            ),
                            before=None,
                            after=aname,
                            location=nf.location,
                        )
                    )
                else:
                    changes.append(
                        ContractChange(
                            kind="GQL003",
                            classification=CompatibilityClass.POTENTIALLY_BREAKING,
                            side=ChangeSide.REQUEST,
                            subject=_subject("graphql_field", f"{name}.{fname}"),
                            path=f"argument:{name}.{fname}({aname})",
                            detail=(
                                f"optional argument added: {name}.{fname}({aname})"
                            ),
                            before=None,
                            after=aname,
                            location=nf.location,
                        )
                    )
            for aname in sorted(set(old_args) & set(new_args)):
                oa, na = old_args[aname], new_args[aname]
                if oa.type.nullable and not na.type.nullable and not na.has_default:
                    changes.append(
                        ContractChange(
                            kind="GQL004",
                            classification=CompatibilityClass.BREAKING,
                            side=ChangeSide.REQUEST,
                            subject=_subject("graphql_field", f"{name}.{fname}"),
                            path=f"argument:{name}.{fname}({aname})",
                            detail=(
                                f"argument nullable->non-null: "
                                f"{name}.{fname}({aname}) (request position)"
                            ),
                            before="nullable",
                            after="non-null",
                            location=nf.location,
                        )
                    )
    return tuple(changes)
