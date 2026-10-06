"""Fleet intelligence tests (spec 025, §110-§115, §190-§191).

Positive: six fleet questions answered with evidence; portfolio per
member; complexity signals are opportunities; deprecation readiness
distinguishes no-clients from no-evidence; external hosts sanitized.
Negative: missing members propagate UNKNOWN; no runtime input yields
UNKNOWN, not fabricated counts. Boundary: single-repo (no manifest)
still answers what it can.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Finding,
    Severity,
)
from forge_doctor_api.fleet import (
    build_fleet_report,
    fleet_health_counts,
    sanitize_host,
)
from forge_doctor_api.workspace import load_workspace

CLOCK = lambda: datetime(2026, 10, 3, tzinfo=UTC)  # noqa: E731

MANIFEST = """name: shop-platform
members:
  - {name: shop-api, path: shop-api, role: service}
  - {name: legacy-api, path: legacy-api, role: service}
  - {name: mobile, path: mobile, role: client}
  - {name: gw, path: gw, role: gateway}
  - {name: gone, path: gone, role: service}
"""

SHOP_API = """openapi: "3.0.3"
info: {title: Shop, version: "2.0", x-owner: shop-team}
paths:
  /items:
    get:
      operationId: items
      security: [{k: []}]
      responses: {'200': {description: ok}}
  /public/ping:
    get:
      operationId: ping
      description: health probe
      responses: {'200': {description: ok}}
components:
  securitySchemes: {k: {type: apiKey, in: header, name: X-K}}
"""

LEGACY_API = """openapi: "3.0.3"
info: {title: Legacy, version: "0.9", deprecated: true,
       x-deprecation-date: "2026-06-01", x-sunset-date: "2027-01-01",
       x-replacement: shop-api}
paths:
  /old:
    get:
      operationId: old
      responses: {'200': {description: ok}}
"""

MOBILE = (
    "import requests\n"
    "r1 = requests.get('https://api.example.com/v1/old')\n"
    "r2 = requests.get('https://api.example.com/v1/items')\n"
)

GW = "routes:\n  - prefix: /items\n"

EXT_CFG = """external_apis:
  - host: "https://user:secret@maps.example.com/v2?key=abc"
    operations: [/geocode]
    timeout: 500
"""


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _report(tmp_path: Path, extra: dict[str, str] | None = None, **kwargs):
    files = {
        "forge-doctor-api.workspace.yaml": MANIFEST,
        "shop-api/api.yaml": SHOP_API,
        "legacy-api/api.yaml": LEGACY_API,
        "mobile/m.py": MOBILE,
        "gw/envoy.yaml": GW,
    }
    files.update(extra or {})
    root = _write(tmp_path / "ws", files)
    ctx = ProjectContext.from_root(root, clock=CLOCK)
    ws = load_workspace(ctx)
    assert ws is not None
    return build_fleet_report(ctx, ws, **kwargs)


def _question(report, key: str):
    return next(q for q in report.questions if q.key == key)


# -- §110 six questions ----------------------------------------------------------


def test_six_questions_answered(tmp_path: Path) -> None:
    rep = _report(tmp_path)
    assert {q.key for q in rep.questions} == {
        "public_apis", "unowned_apis", "unauthenticated_operations",
        "deprecated_versions", "regressing_endpoints", "shared_external_apis",
    }
    public = _question(rep, "public_apis")
    assert any(e.repo == "legacy-api" for e in public.entries)  # /old has no security
    shop = next(e for e in public.entries if e.repo == "shop-api")
    assert "1/2" in shop.detail  # /items secured, /public/ping not

    unowned = _question(rep, "unowned_apis")
    assert any(e.repo == "legacy-api" for e in unowned.entries)
    assert not any(e.repo == "shop-api" for e in unowned.entries)  # has x-owner


def test_missing_member_propagates_unknown(tmp_path: Path) -> None:
    rep = _report(tmp_path)
    assert rep.members_missing == ("gone",)
    assert any(u.subject == "gone" for u in rep.unknowns)


def test_regressing_endpoints(tmp_path: Path) -> None:
    rep = _report(
        tmp_path,
        regressions={"shop-api": ("GET /items", "GET /items", "GET /other")},
    )
    entries = _question(rep, "regressing_endpoints").entries
    assert [e.subject for e in entries] == ["GET /items"]  # only 2x counts


def test_regressing_without_runtime_is_unknown(tmp_path: Path) -> None:
    rep = _report(tmp_path)
    q = _question(rep, "regressing_endpoints")
    assert q.entries == () and q.unknowns


def test_shared_external_api(tmp_path: Path) -> None:
    rep = _report(tmp_path, {
        "shop-api/ext.yaml": EXT_CFG,
        "legacy-api/ext.yaml": EXT_CFG,
    })
    q = _question(rep, "shared_external_apis")
    assert q.entries and "maps.example.com" in q.entries[0].subject
    assert "legacy-api" in q.entries[0].detail and "shop-api" in q.entries[0].detail


# -- §111 portfolio --------------------------------------------------------------


def test_portfolio_per_member(tmp_path: Path) -> None:
    rep = _report(tmp_path)
    by_repo = {m.repo: m for m in rep.portfolio}
    assert by_repo["shop-api"].styles == ("rest",)
    assert by_repo["shop-api"].operations == 2
    assert by_repo["shop-api"].owner == "shop-team"
    assert by_repo["gw"].gateways == 1
    assert "gone" not in by_repo  # missing member absent from portfolio
    assert rep.members_missing == ("gone",)


def test_portfolio_multi_style(tmp_path: Path) -> None:
    rep = _report(tmp_path, {
        "shop-api/svc.proto": 'syntax = "proto3";\nservice S {}\n',
    })
    by_repo = {m.repo: m for m in rep.portfolio}
    assert "grpc" in by_repo["shop-api"].styles
    assert "rest" in by_repo["shop-api"].styles


# -- §112 complexity signals -----------------------------------------------------


def test_complexity_signals_are_opportunities(tmp_path: Path) -> None:
    rep = _report(tmp_path, {
        "shop-api/svc.proto": 'syntax = "proto3";\nservice S {}\n',
        "shop-api/ext.yaml": EXT_CFG,
        "legacy-api/ext.yaml": EXT_CFG,
        "gw2/d.yaml": GW,  # not a member — must not count
        "forge-doctor-api.workspace.yaml": MANIFEST + "  - {name: gw2, path: gw2, role: gateway}\n",
    })
    kinds = {s.kind for s in rep.complexity}
    assert "multi_protocol" in kinds
    assert "shared_external_dependency" in kinds
    assert "gateway_chain" in kinds
    # every complexity signal carries evidence; none are findings
    assert all(s.evidence for s in rep.complexity)


def test_multiple_auth_models_signal(tmp_path: Path) -> None:
    rep = _report(tmp_path, {
        "legacy-api/api.yaml": LEGACY_API.replace(
            "responses: {'200': {description: ok}}",
            "security: [{o: []}]\n      responses: {'200': {description: ok}}",
        ).replace(
            "x-replacement: shop-api}",
            'x-replacement: shop-api}\ncomponents:\n'
            '  securitySchemes: {o: {type: oauth2, flows: {implicit: '
            '{authorizationUrl: "https://x", scopes: {}}}}}',
        ),
    })
    kinds = {s.kind for s in rep.complexity}
    assert "multiple_auth_models" in kinds


# -- §114 deprecation readiness --------------------------------------------------


def test_deprecation_readiness(tmp_path: Path) -> None:
    rep = _report(tmp_path)
    dep = next(d for d in rep.deprecations if d.repo == "legacy-api")
    assert dep.remaining_clients == 1  # mobile's `m` client calls /old
    assert dep.remaining_client_subjects == ("m",)
    assert dep.replacement == "shop-api"
    assert dep.contract_age_days == 124  # 2026-06-01 -> 2026-10-03
    assert dep.observed_traffic is None  # no runtime -> UNKNOWN
    assert any("runtime" in u.missing for u in dep.unknowns)


def test_deprecation_no_clients_vs_no_evidence(tmp_path: Path) -> None:
    """Review note: 'no clients found' differs from 'no client evidence'."""
    rep = _report(tmp_path, {
        "forge-doctor-api.workspace.yaml": MANIFEST.replace(
            "  - {name: mobile, path: mobile, role: client}\n", ""
        ),
    })
    dep = next(d for d in rep.deprecations if d.repo == "legacy-api")
    assert dep.remaining_clients is None  # no client repos -> UNKNOWN
    assert any("client" in u.missing for u in dep.unknowns)


# -- §115 external APIs -----------------------------------------------------------


def test_external_api_sanitized_and_candidates(tmp_path: Path) -> None:
    rep = _report(tmp_path, {"shop-api/ext.yaml": EXT_CFG})
    ext = next(e for e in rep.external_apis if e.repo == "shop-api")
    assert "user:secret" not in ext.host  # userinfo stripped
    assert "key=abc" not in ext.host      # query stripped
    assert ext.host == "https://maps.example.com/v2"
    assert ext.timeout_ms == 500
    assert ext.has_retry is False
    assert any("[candidate]" in s for s in ext.signals)


def test_sanitize_host() -> None:
    assert sanitize_host("https://u:p@h.example.com/x?y=1#z") == \
        "https://h.example.com/x"
    assert sanitize_host("plain.example.com") == "plain.example.com"


# -- §190 quality + §191 health ---------------------------------------------------


def test_quality_dimensions_no_score(tmp_path: Path) -> None:
    rep = _report(tmp_path)
    dims = {(d.repo, d.name): d for d in rep.quality}
    assert ("shop-api", "contract completeness") in dims
    assert (
        dims[("shop-api", "contract completeness")].value
        == "2/2 operations have operationId"
    )
    assert ("legacy-api", "ownership") in dims
    assert dims[("legacy-api", "ownership")].value == "unknown"
    assert not hasattr(rep, "score")  # §191: no composite number


def test_health_counts(tmp_path: Path) -> None:
    findings = (
        Finding(id="COMPAT001", title="t", description="d",
                severity=Severity.HIGH, confidence=Confidence.HIGH,
                evidence_kind=EvidenceKind.STATIC, unknowns=()),
        Finding(id="RELAPI002", title="t", description="d",
                severity=Severity.MEDIUM, confidence=Confidence.HIGH,
                evidence_kind=EvidenceKind.CONFIG),
        Finding(id="APISEC001", title="t", description="d",
                severity=Severity.HIGH, confidence=Confidence.LOW,
                evidence_kind=EvidenceKind.STATIC),
        Finding(id="APIPERF001", title="t", description="d",
                severity=Severity.MEDIUM, confidence=Confidence.HIGH,
                evidence_kind=EvidenceKind.RUNTIME),
        Finding(id="OAS001", title="t", description="d",
                severity=Severity.LOW, confidence=Confidence.HIGH,
                evidence_kind=EvidenceKind.STATIC),
    )
    h = fleet_health_counts(findings)
    assert h.breaking_changes == 1 and h.reliability_gaps == 1
    assert h.security_candidates == 1 and h.runtime_regressions == 1


# -- §159 inventory CLI ------------------------------------------------------------


def test_inventory_cli(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from forge_doctor_api.cli import app

    root = _write(tmp_path / "ws", {
        "forge-doctor-api.workspace.yaml": MANIFEST,
        "shop-api/api.yaml": SHOP_API,
        "legacy-api/api.yaml": LEGACY_API,
    })
    runner = CliRunner()
    res = runner.invoke(app, ["inventory", str(root)])
    assert res.exit_code == 0, res.output
    assert "shop-api" in res.output and "legacy-api" in res.output
    res_json = runner.invoke(app, ["inventory", str(root), "--json"])
    assert res_json.exit_code == 0
    assert '"workspace": "shop-platform"' in res_json.output


def test_inventory_single_repo(tmp_path: Path) -> None:
    """No manifest -> the root itself is one mixed member."""
    from typer.testing import CliRunner

    from forge_doctor_api.cli import app

    root = _write(tmp_path / "solo", {"api.yaml": SHOP_API})
    res = CliRunner().invoke(app, ["inventory", str(root)])
    assert res.exit_code == 0, res.output
    assert "solo" in res.output
