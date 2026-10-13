"""§126-§127 knowledge pack models.

Every mutable fact carries provenance: `source`, `source_version`,
`last_verified`, `effective_since`, `deprecated_since`. Packs are bundled
YAML data — loaded via importlib.resources, never fetched live (§129).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from forge_doctor_api.core.models import Model, ModelError, _require_text

REQUIRED_PROVENANCE = ("source", "source_version", "last_verified")
OPTIONAL_PROVENANCE = ("effective_since", "deprecated_since")

# §193 domain maturity stages, tracked internally on each pack.
MATURITY_STAGES = (
    "detection",
    "semantic-model",
    "checks",
    "graph",
    "runtime",
    "cross-domain",
    "migration",
)


def _date(value: object, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ModelError(
            f"provenance {field_name} must be an ISO date: {value!r}"
        ) from exc


@dataclass(frozen=True, kw_only=True)
class PackProvenance(Model):
    """§127 provenance for one mutable fact."""

    source: str
    source_version: str
    last_verified: date
    effective_since: date | None = None
    deprecated_since: date | None = None

    def __post_init__(self) -> None:
        _require_text("PackProvenance.source", self.source)
        _require_text("PackProvenance.source_version", self.source_version)

    @classmethod
    def parse(cls, raw: object, entry_id: str) -> PackProvenance:
        doc = raw if isinstance(raw, dict) else {}
        missing = [k for k in REQUIRED_PROVENANCE if doc.get(k) in (None, "")]
        if missing:
            raise ModelError(
                f"pack entry {entry_id!r} missing provenance: "
                f"{', '.join(missing)}"
            )
        return cls(
            source=str(doc["source"]),
            source_version=str(doc["source_version"]),
            last_verified=_date(doc["last_verified"], "last_verified") or date.min,
            effective_since=_date(doc.get("effective_since"), "effective_since"),
            deprecated_since=_date(
                doc.get("deprecated_since"), "deprecated_since"
            ),
        )

    def age_days(self, today: date) -> int:
        return (today - self.last_verified).days


@dataclass(frozen=True, kw_only=True)
class PackEntry(Model):
    """One mutable fact: opaque `fields` payload + mandatory provenance."""

    id: str
    fields: dict[str, Any] = field(default_factory=dict)
    provenance: PackProvenance

    def __post_init__(self) -> None:
        _require_text("PackEntry.id", self.id)


@dataclass(frozen=True, kw_only=True)
class KnowledgePack(Model):
    """One bundled pack document under `knowledge/<domain>/`."""

    name: str
    domain: str
    edition: str
    maturity: str = "detection"
    entries: tuple[PackEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_text("KnowledgePack.name", self.name)
        _require_text("KnowledgePack.domain", self.domain)
        _require_text("KnowledgePack.edition", self.edition)
        if self.maturity not in MATURITY_STAGES:
            raise ModelError(
                f"KnowledgePack.maturity must be one of "
                f"{MATURITY_STAGES}: {self.maturity!r}"
            )

    def entry(self, entry_id: str) -> PackEntry | None:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    def stale_entries(self, today: date, max_age_days: int) -> tuple[PackEntry, ...]:
        """Entries whose `last_verified` is older than `max_age_days` (§127)."""
        return tuple(
            e for e in self.entries
            if e.provenance.age_days(today) > max_age_days
        )
