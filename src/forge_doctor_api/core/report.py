"""Compact domain projection shared by the unified report (§16)."""

from __future__ import annotations

from dataclasses import dataclass

from forge_doctor_api.core.models import Model


@dataclass(frozen=True, kw_only=True)
class DomainSummary(Model):
    """Compact projection of one analyzer domain.

    `counts`: label -> number (e.g. ("operations", 42)).
    `ids`: stable entity/operation identifiers (never payloads).
    `summaries`: one-line headline strings.
    `unknowns`: count of UnknownFacts the domain contributed.
    """

    counts: tuple[tuple[str, int], ...] = ()
    ids: tuple[str, ...] = ()
    summaries: tuple[str, ...] = ()
    unknowns: int = 0
