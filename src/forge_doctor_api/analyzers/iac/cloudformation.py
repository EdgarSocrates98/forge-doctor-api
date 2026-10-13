"""CloudFormation surface parser (spec 055).

YAML `Resources:` → infra entities + literal attribute candidates.
CloudFormation intrinsic tags (``!Ref``, ``!GetAtt``, ``!Sub`` ...)
are *dynamic*: a custom loader rewrites them as
``{"Ref": ...}``-shaped dicts marked dynamic — never resolved,
never crashed on, and each emits an UnknownFact only where a literal
was required. Malformed templates yield a parse UnknownFact, not a
crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from forge_doctor_api.core.models import SourceLocation, UnknownFact

_CFN_TAG = "tag:forge-doctor-api,cfn:"


class _CfnLoader(yaml.SafeLoader):
    """SafeLoader that turns `!Tag` into {"!Tag": value} dicts."""


def _unknown_tag(loader: yaml.Loader, suffix: str,
                 node: yaml.Node) -> dict[str, Any]:
    if isinstance(node, yaml.ScalarNode):
        inner: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        inner = loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        inner = loader.construct_mapping(node)
    else:
        inner = None
    return {f"!{suffix}": inner}


_CfnLoader.add_multi_constructor("!", _unknown_tag)

_DYNAMIC_KEYS = ("Ref", "Fn::GetAtt", "Fn::Sub", "Fn::ImportValue",
                 "Fn::If", "Fn::FindInMap", "Fn::Select",
                 "Fn::Base64", "Fn::Cidr", "Fn::GetAZs",
                 "Fn::Transform")


@dataclass(frozen=True, kw_only=True)
class CfnAttr:
    name: str
    value: str | None          # scalar literal, else None (dynamic)
    location: SourceLocation
    dynamic: bool = False


@dataclass(frozen=True, kw_only=True)
class CfnResource:
    type_name: str             # e.g. "AWS::ElasticLoadBalancingV2::LoadBalancer"
    logical_id: str
    attrs: tuple[CfnAttr, ...]
    location: SourceLocation


def _flatten_props(props: dict[str, Any], prefix: str,
                   path: str, out: list[CfnAttr],
                   unknowns: list[UnknownFact], rid: str,
                   depth: int = 0) -> None:
    if depth > 6:
        return
    for key in sorted(props):
        val = props[key]
        name = f"{prefix}{key}" if prefix else key
        if isinstance(val, dict):
            tags = set(val) & set(_DYNAMIC_KEYS) | {
                k for k in val if k.startswith("!")}
            if tags:
                out.append(CfnAttr(
                    name=name, value=None, dynamic=True,
                    location=SourceLocation(path=path, line=None)))
                unknowns.append(UnknownFact(
                    subject=f"{rid}.{name}",
                    missing="literal property value",
                    resolution=f"intrinsic {sorted(tags)[0]} is not "
                               "resolved"))
            else:
                _flatten_props(val, f"{name}.", path, out, unknowns,
                               rid, depth + 1)
        elif isinstance(val, list):
            if all(isinstance(v, (str, int, float, bool))
                   for v in val):
                out.append(CfnAttr(
                    name=name, value="[" + ",".join(str(v) for v in val) + "]",
                    location=SourceLocation(path=path, line=None)))
            else:
                out.append(CfnAttr(
                    name=name, value=None, dynamic=True,
                    location=SourceLocation(path=path, line=None)))
        elif isinstance(val, (str, int, float, bool)) or val is None:
            out.append(CfnAttr(
                name=name,
                value=None if val is None else str(val),
                location=SourceLocation(path=path, line=None)))


def parse_cfn(path: str, text: str) -> tuple[tuple[CfnResource, ...],
                                             tuple[UnknownFact, ...]]:
    """Parse a CloudFormation template into resources + attrs."""
    try:
        doc = yaml.load(text, Loader=_CfnLoader)
    except yaml.YAMLError as e:
        return (), (UnknownFact(
            subject=path, missing="parseable CloudFormation template",
            resolution=f"YAML error: {type(e).__name__}"),)
    if not isinstance(doc, dict):
        return (), ()
    resources = doc.get("Resources")
    if not isinstance(resources, dict):
        return (), ()
    out: list[CfnResource] = []
    unknowns: list[UnknownFact] = []
    for logical_id in sorted(resources):
        body = resources[logical_id]
        if not isinstance(body, dict):
            continue
        rtype = body.get("Type")
        if not isinstance(rtype, str):
            unknowns.append(UnknownFact(
                subject=f"{logical_id}",
                missing="resource Type",
                resolution="Type must be a literal string"))
            continue
        attrs: list[CfnAttr] = []
        props = body.get("Properties")
        if isinstance(props, dict):
            _flatten_props(props, "", path, attrs, unknowns, logical_id)
        if "Condition" in body:
            unknowns.append(UnknownFact(
                subject=logical_id,
                missing="resource existence (Condition)",
                resolution="conditions are not evaluated"))
        out.append(CfnResource(
            type_name=rtype, logical_id=str(logical_id),
            attrs=tuple(attrs),
            location=SourceLocation(path=path, line=None)))
    return tuple(out), tuple(unknowns)


def looks_like_cfn(text: str) -> bool:
    """Cheap marker check before the YAML attempt."""
    return ("AWSTemplateFormatVersion" in text
            or ("AWS::" in text and "Resources:" in text))
