"""Knowledge pack + capability tests (spec 027, §126-§130, §174, §193).

Positive: packs load with validated §127 provenance; analyzer facades are
pack-backed; capability detection is evidence-bearing; dependency gaps
surface. Negative: malformed pack, missing provenance, stale facts.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from forge_doctor_api.analyzers.asyncapi.knowledge import (
    KNOWN_BINDINGS,
)
from forge_doctor_api.analyzers.asyncapi.knowledge import (
    SUPPORTED_FAMILIES as ASYNC_FAMILIES,
)
from forge_doctor_api.analyzers.openapi.knowledge import (
    HTTP_METHODS_3_2,
    version_family,
)
from forge_doctor_api.analyzers.openapi.knowledge import (
    SUPPORTED_FAMILIES as OAS_FAMILIES,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.export import export_findings
from forge_doctor_api.core.models import ModelError
from forge_doctor_api.knowledge import (
    Capability,
    DependencyRule,
    detect_capabilities,
    knowledge_versions,
    load_pack,
    pack_capabilities,
    parse_pack,
)
from forge_doctor_api.reliability import load_reliability_model
from forge_doctor_api.security.knowledge import (
    check_to_owasp,
    owasp_categories,
)


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


# --- pack loader (§126-§127) --------------------------------------------------


def test_pack_loads_with_provenance() -> None:
    pack = load_pack("openapi", "versions.yaml")
    assert pack.name == "openapi-versions"
    assert pack.domain == "openapi"
    assert pack.maturity in ("cross-domain", "checks", "detection")
    assert len(pack.entries) == 4
    entry = pack.entry("openapi-3.2")
    assert entry is not None
    assert entry.provenance.source_version == "3.2.1"
    assert entry.provenance.last_verified == date(2026, 9, 30)


def test_every_bundled_entry_has_full_provenance() -> None:
    """§127: every mutable fact carries source/version/last_verified."""
    from forge_doctor_api.knowledge import all_packs

    packs = all_packs()
    assert len(packs) >= 13
    for pack in packs:
        assert pack.entries, f"{pack.name} has no entries"
        for entry in pack.entries:
            assert entry.provenance.source
            assert entry.provenance.source_version
            assert entry.provenance.last_verified > date(2020, 1, 1)


def test_malformed_pack_rejected() -> None:
    with pytest.raises(ModelError, match="entries"):
        parse_pack({"pack": "x", "domain": "d", "edition": "1"}, "t")


def test_missing_provenance_rejected() -> None:
    doc = {
        "pack": "x", "domain": "d", "edition": "1",
        "entries": {"e": {"fields": {}, "provenance": {"source": "s"}}},
    }
    with pytest.raises(ModelError, match="provenance"):
        parse_pack(doc, "t")


def test_missing_pack_raises() -> None:
    with pytest.raises(ModelError, match="not found"):
        load_pack("openapi", "nonexistent.yaml")


def test_stale_entries_flagged() -> None:
    pack = load_pack("security", "owasp_api_top10.yaml")
    fresh = pack.stale_entries(date(2026, 9, 20), max_age_days=30)
    assert fresh == ()
    stale = pack.stale_entries(date(2027, 9, 20), max_age_days=30)
    assert len(stale) == len(pack.entries)


# --- pack-backed analyzer facades ---------------------------------------------


def test_openapi_version_facts_come_from_pack() -> None:
    assert OAS_FAMILIES == ("3.0", "3.1", "3.2")
    assert "query" in HTTP_METHODS_3_2  # 3.2 adds the query method
    assert version_family("3.2.1") == "3.2"
    assert version_family("4.0.0") is None
    assert version_family("bogus") is None


def test_asyncapi_facts_come_from_pack() -> None:
    assert "3.0" in ASYNC_FAMILIES and "2.6" in ASYNC_FAMILIES
    assert "kafka" in KNOWN_BINDINGS


def test_owasp_pack_drives_check_mapping() -> None:
    """Review note: spec 018's mapping reads the pack, not constants."""
    cats = owasp_categories()
    assert cats["API1"] == "Broken Object Level Authorization"
    assert check_to_owasp("APISEC001") == ("API1",)
    assert check_to_owasp("NOPE001") == ()


# --- §174 knowledge versions in exports ---------------------------------------


def test_export_carries_knowledge_versions() -> None:
    versions = export_findings([]).knowledge_versions
    assert versions["openapi-versions"] == "2026.10"
    assert versions["owasp-api-security-top-10"] == "2023"


def test_knowledge_versions_cover_all_domains() -> None:
    versions = knowledge_versions()
    assert "envoy-capabilities" in versions
    assert "openapi-versions" in versions
    assert "owasp-api-security-top-10" in versions


# --- §69-§70 capability engine -------------------------------------------------


def test_capability_retry_gap_without_idempotency(tmp_path: Path) -> None:
    """§70: SAFE_RETRY REQUIRES IDEMPOTENT_OPERATION -> gap when absent."""
    root = _write(tmp_path / "p", {
        "cfg.yaml": "retries: [{scope: gw, max_attempts: 3}]\n",
    })
    ctx = ProjectContext.from_root(root)
    model = load_reliability_model(ctx, ["cfg.yaml"])
    report = detect_capabilities(reliability=model)
    caps = {c.capability for c in report.capabilities}
    assert Capability.RETRY in caps
    gap = [g for g in report.gaps if g.rule is DependencyRule.SAFE_RETRY]
    assert gap and gap[0].missing is Capability.IDEMPOTENT_OPERATION
    assert gap[0].unknowns


def test_capability_gap_closes_with_idempotency(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "cfg.yaml": (
            "retries: [{scope: gw, max_attempts: 2}]\n"
            "idempotency:\n"
            "  idempotent: true\n"
        ),
    })
    ctx = ProjectContext.from_root(root)
    model = load_reliability_model(ctx, ["cfg.yaml"])
    report = detect_capabilities(reliability=model)
    assert Capability.RETRY in {c.capability for c in report.capabilities}
    assert all(
        g.rule is not DependencyRule.SAFE_RETRY for g in report.gaps
    )


def test_no_models_no_capabilities() -> None:
    report = detect_capabilities()
    assert report.capabilities == () and report.gaps == ()


def test_capabilities_carry_evidence(tmp_path: Path) -> None:
    root = _write(tmp_path / "p", {
        "cfg.yaml": "retries: [{scope: gw, max_attempts: 3}]\n",
    })
    model = load_reliability_model(
        ProjectContext.from_root(root), ["cfg.yaml"]
    )
    report = detect_capabilities(reliability=model)
    retry = next(c for c in report.capabilities
                 if c.capability is Capability.RETRY)
    assert retry.evidence and all(e.source for e in retry.evidence)


# --- §130 capability packs -----------------------------------------------------


def test_capability_packs_reference_data() -> None:
    assert "hedging" in pack_capabilities("envoy")
    assert "rate-limiting" in pack_capabilities("kong")
    assert pack_capabilities("made-up-gateway") == ()


def test_maturity_stages_tracked() -> None:
    """§193: packs declare a maturity stage from the fixed ladder."""
    from forge_doctor_api.knowledge import MATURITY_STAGES, all_packs

    assert MATURITY_STAGES[0] == "detection"
    assert MATURITY_STAGES[-1] == "migration"
    for p in all_packs():
        assert p.maturity in MATURITY_STAGES
