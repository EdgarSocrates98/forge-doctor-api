"""§126-§129 pack loader: bundled YAML under `knowledge/<domain>/`.

Loading is hermetic — `importlib.resources` only, no filesystem access,
no fetching. A malformed document or missing §127 provenance raises
`ModelError` (packs are reviewed data, not executable code).
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import yaml

from forge_doctor_api.core.models import ModelError
from forge_doctor_api.knowledge.model import (
    KnowledgePack,
    PackEntry,
    PackProvenance,
)

_PACKAGE = "forge_doctor_api.knowledge"
_KNOWN_DOMAINS = (
    "asyncapi",
    "frameworks",
    "gateways",
    "graphql",
    "grpc",
    "http",
    "jsonschema",
    "openapi",
    "security",
)


def _read(domain: str, filename: str) -> dict[str, Any]:
    try:
        text = (
            resources.files(_PACKAGE)
            .joinpath(domain)
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, NotADirectoryError, ModuleNotFoundError) as exc:
        raise ModelError(
            f"knowledge pack not found: {domain}/{filename}"
        ) from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ModelError(
            f"malformed knowledge pack {domain}/{filename}: {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise ModelError(
            f"knowledge pack {domain}/{filename} is not a mapping"
        )
    return doc


def parse_pack(doc: dict[str, Any], where: str) -> KnowledgePack:
    """Validate one pack document (§126 header + §127 per-entry provenance)."""
    name, domain, edition = (
        doc.get("pack"), doc.get("domain"), doc.get("edition")
    )
    for key, value in (("pack", name), ("domain", domain), ("edition", edition)):
        if value in (None, ""):
            raise ModelError(f"knowledge pack {where} missing `{key}`")
    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, dict):
        raise ModelError(f"knowledge pack {where} missing `entries` mapping")
    entries = []
    for entry_id in sorted(raw_entries):
        raw = raw_entries[entry_id]
        if not isinstance(raw, dict):
            raise ModelError(
                f"pack entry {entry_id!r} in {where} is not a mapping"
            )
        raw_fields = raw.get("fields")
        if not isinstance(raw_fields, dict):
            raise ModelError(
                f"pack entry {entry_id!r} in {where} missing `fields` mapping"
            )
        entries.append(
            PackEntry(
                id=str(entry_id),
                fields={str(k): v for k, v in raw_fields.items()},
                provenance=PackProvenance.parse(raw.get("provenance"), str(entry_id)),
            )
        )
    return KnowledgePack(
        name=str(name),
        domain=str(domain),
        edition=str(edition),
        maturity=str(doc.get("maturity") or "detection"),
        entries=tuple(entries),
    )


def load_pack(domain: str, filename: str) -> KnowledgePack:
    """Load one pack file; raises ModelError on any schema violation."""
    return parse_pack(_read(domain, filename), f"{domain}/{filename}")


def domain_packs(domain: str) -> tuple[KnowledgePack, ...]:
    """Every pack bundled under `knowledge/<domain>/`, sorted by filename."""
    try:
        files = sorted(
            resources.files(_PACKAGE).joinpath(domain).iterdir(),
            key=lambda p: p.name,
        )
    except (FileNotFoundError, ModuleNotFoundError):
        return ()
    return tuple(
        load_pack(domain, f.name)
        for f in files
        if f.name.endswith((".yaml", ".yml"))
    )


def all_packs() -> tuple[KnowledgePack, ...]:
    """Every bundled pack, domain order fixed by `_KNOWN_DOMAINS`."""
    out: list[KnowledgePack] = []
    for domain in _KNOWN_DOMAINS:
        out.extend(domain_packs(domain))
    return tuple(out)


def knowledge_versions() -> dict[str, str]:
    """§174 export metadata: `pack name -> edition` for every bundled pack."""
    return {pack.name: pack.edition for pack in all_packs()}
