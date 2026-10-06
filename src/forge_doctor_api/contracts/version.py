"""forge-contracts/1 version negotiation — canonical wire semantics.

Every contract family is ``<name>/<major>`` — e.g. ``forge-contracts/1``.
Two versions are wire-compatible when family *and* major match; additive
fields never bump major, removed/renamed fields always do. Negotiation
picks the newest shared version or fails explicitly — never a silent
partial decode.

This module mirrors the canonical contract (spec 074): it is vendored
wire semantics, not an import of ``forge_doctor_data`` — the two
doctors share the *contract*, not each other's packages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class ContractVersion:
    """An opaque ``family/major`` contract identifier."""

    family: str
    major: int

    def __str__(self) -> str:
        return f"{self.family}/{self.major}"

    @staticmethod
    def parse(text: str) -> ContractVersion:
        family, sep, major = text.rpartition("/")
        if not sep or not family or not major.isdigit():
            raise ValueError(
                f"invalid contract version: {text!r} "
                "(expected <family>/<major>)"
            )
        return ContractVersion(family, int(major))

    def compatible_with(self, other: ContractVersion) -> bool:
        return self.family == other.family and self.major == other.major


# The shared contract surface this doctor speaks on the wire.
CURRENT = ContractVersion("forge-contracts", 1)
SUPPORTED: tuple[ContractVersion, ...] = (CURRENT,)
SUPPORTED_MIN: ContractVersion = min(SUPPORTED)
SUPPORTED_MAX: ContractVersion = max(SUPPORTED)


def negotiate(
    offered: str | ContractVersion,
    supported: tuple[ContractVersion, ...] = SUPPORTED,
) -> ContractVersion | None:
    """Return the common version for ``offered`` or ``None`` when disjoint."""
    version = (
        offered
        if isinstance(offered, ContractVersion)
        else ContractVersion.parse(offered)
    )
    candidates = [v for v in supported if v.compatible_with(version)]
    return max(candidates) if candidates else None


def within_range(offered: str | ContractVersion) -> bool:
    """Whether ``offered`` falls inside the declared ``[min, max]`` window."""
    version = (
        offered
        if isinstance(offered, ContractVersion)
        else ContractVersion.parse(offered)
    )
    return version.family == CURRENT.family and (
        SUPPORTED_MIN.major <= version.major <= SUPPORTED_MAX.major
    )
