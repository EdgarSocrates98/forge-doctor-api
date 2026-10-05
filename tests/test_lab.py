"""Lab harness tests (spec 026, §98-§101, §199-§202).

The harness is itself under test: scenario discovery, ground-truth
parsing, expected/forbidden matching (order-tolerant, content-strict),
per-family precision/recall, run-record persistence — plus a full
corpus pass over the repository `labs/` tree, which must be green.
"""

from __future__ import annotations

import json
from pathlib import Path

from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import (
    Confidence,
    EvidenceKind,
    Finding,
    Severity,
)
from forge_doctor_api.lab import (
    FamilyScore,
    LabObservations,
    LabScenario,
    aggregate_scores,
    compare,
    discover_scenarios,
    run_labs,
    write_run_record,
)
from forge_doctor_api.lab.runner import run_scenario

REPO_LABS = Path(__file__).resolve().parent.parent / "labs"


def _finding(check_id: str, description: str = "") -> Finding:
    return Finding(
        id=check_id,
        title=check_id,
        description=description or check_id,
        severity=Severity.LOW,
        confidence=Confidence.LOW,
        evidence_kind=EvidenceKind.STATIC,
    )


def _scenario(**expected: object) -> LabScenario:
    from forge_doctor_api.lab.model import LabExpectation

    return LabScenario(
        domain="t", name="s", path="t/s",
        expected=LabExpectation(**expected),
    )


def _write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


# --- discovery + ground truth ------------------------------------------------


def test_discovery_finds_scenarios_sorted(tmp_path: Path) -> None:
    root = _write(tmp_path / "labs", {
        "b/second/expected.yaml": "expected_findings: []",
        "a/first/expected.yaml": "expected_findings: [OAS001]",
        "a/first/api.yaml": "x: 1",
        "notascenario/readme.txt": "no expected.yaml",
    })
    scenarios = discover_scenarios(ProjectContext.from_root(root))
    assert [s.path for s in scenarios] == ["a/first", "b/second"]
    assert scenarios[0].expected.findings == ("OAS001",)
    assert scenarios[0].domain == "a"


def test_ground_truth_parses_all_fields(tmp_path: Path) -> None:
    root = _write(tmp_path / "labs", {
        "d/s/expected.yaml": (
            "run: [openapi]\n"
            "diff: {old: before, new: after}\n"
            "hops: [gw, svc]\n"
            "today: '2030-01-01'\n"
            "expected_findings: [OAS001, 'APISEC*']\n"
            "forbidden_findings: ['GQL*']\n"
            "expected_entities: [endpoint:x]\n"
            "forbidden_entities: [endpoint:y]\n"
            "expected_clients: [web]\n"
            "expected_breaking: [getUser]\n"
            "expected_runtime_signals: [tracing]\n"
            "expected_issues: [MALFORMED]\n"
            "expected_description_contains: [BOLA]\n"
            "forbidden_description_contains: [confirmed]\n"
        ),
    })
    (s,) = discover_scenarios(ProjectContext.from_root(root))
    assert s.run == ("openapi",)
    assert (s.diff_old, s.diff_new) == ("before", "after")
    assert s.hops == ("gw", "svc")
    assert s.today == "2030-01-01"
    assert s.expected.findings == ("OAS001", "APISEC*")
    assert s.expected.forbidden_findings == ("GQL*",)
    assert s.expected.forbidden_entities == ("endpoint:y",)
    assert s.expected.issues == ("MALFORMED",)
    assert s.expected.forbidden_description_contains == ("confirmed",)


def test_unparseable_expected_yields_empty_scenario(tmp_path: Path) -> None:
    root = _write(tmp_path / "labs", {
        "d/s/expected.yaml": "{unclosed",
        "d/s/api.yaml": "x: 1",
    })
    (s,) = discover_scenarios(ProjectContext.from_root(root))
    assert s.name == "s"
    assert s.expected.findings == ()


# --- compare: both directions binding, order-insensitive ---------------------


def test_compare_hits_and_misses() -> None:
    s = _scenario(findings=("OAS001", "OAS002"))
    obs = LabObservations(findings=[_finding("OAS001")])
    r = compare(s, obs)
    assert not r.passed
    assert r.missing_findings == ("OAS002",)


def test_compare_forbidden_hit_fails() -> None:
    s = _scenario(forbidden_findings=("OAS*",))
    obs = LabObservations(findings=[_finding("OAS013")])
    r = compare(s, obs)
    assert not r.passed
    assert r.forbidden_hits == ("OAS013",)


def test_compare_unexpected_finding_fails_even_when_expected_empty() -> None:
    s = _scenario()
    obs = LabObservations(findings=[_finding("APISEC007")])
    r = compare(s, obs)
    assert not r.passed
    assert r.unexpected_findings == ("APISEC007",)


def test_compare_is_order_insensitive() -> None:
    s = _scenario(
        findings=("OAS002", "OAS001"),
        entities=("z-entity", "a-entity"),
    )
    obs = LabObservations(
        findings=[_finding("OAS001"), _finding("OAS002")],
        entities=["a-entity", "z-entity"],
    )
    assert compare(s, obs).passed


def test_compare_content_drift_fails() -> None:
    """Ordering is tolerated; wording is not (§199 + review note)."""
    s = _scenario(
        findings=("APISEC001",),
        description_contains=("BOLA risk candidate",),
        forbidden_description_contains=("confirmed",),
    )
    obs = LabObservations(
        findings=[_finding("APISEC001", "BOLA confirmed - vulnerability")]
    )
    r = compare(s, obs)
    assert not r.passed
    assert len(r.wording_violations) == 2


def test_compare_entities_edges_and_forbidden() -> None:
    s = _scenario(
        entities=("endpoint:GET /a",),
        edges=("EXPOSES",),
        forbidden_entities=("endpoint:DELETE",),
        forbidden_edges=("IMPLEMENTS",),
    )
    obs = LabObservations(
        entities=["endpoint:GET /a", "endpoint:DELETE /a"],
        edges=["EXPOSES:x->y", "IMPLEMENTS:o->e"],
    )
    r = compare(s, obs)
    assert not r.passed
    assert r.forbidden_entity_hits == ("endpoint:DELETE",)
    assert r.forbidden_edge_hits == ("IMPLEMENTS",)


def test_compare_clients_breaking_signals_issues() -> None:
    s = _scenario(
        findings=("APIPERF001",),
        clients=("frontend-service",),
        breaking=("getUser",),
        runtime_signals=("APIPERF001",),
        issues=("MALFORMED",),
    )
    obs = LabObservations(
        clients=["frontend-service"],
        breaking=["operation:getUser"],
        runtime_signals=["tracing"],
        findings=[_finding("APIPERF001")],
        issues=["MALFORMED: bad yaml"],
    )
    assert compare(s, obs).passed


# --- per-family precision/recall (§200) -------------------------------------


def test_family_scores_track_hits_misses_fps() -> None:
    hit = _scenario(findings=("OAS001",))
    miss = _scenario(findings=("OAS002",))
    fp = _scenario(findings=("OAS001",))
    pairs = [
        (hit, compare(hit, LabObservations(findings=[_finding("OAS001")]))),
        (miss, compare(miss, LabObservations(findings=[]))),
        (fp, compare(fp, LabObservations(
            findings=[_finding("OAS001"), _finding("APISEC009")],
        ))),
    ]
    scores = {f.family: f for f in aggregate_scores(pairs)}
    assert scores["OAS"].expected == 3
    assert scores["OAS"].hits == 2
    assert scores["OAS"].misses == 1
    assert scores["OAS"].precision == 1.0
    assert scores["APISEC"].false_positives == 1
    assert scores["APISEC"].precision == 0.0


def test_run_record_written_under_factory_runs(tmp_path: Path) -> None:
    report = run_labs(ProjectContext.from_root(_write(tmp_path / "labs", {
        "t/s/expected.yaml": "expected_findings: []",
    })))
    record = write_run_record(report, tmp_path / "factory" / "runs", "20300101T000000Z")
    data = json.loads(record.read_text())
    assert record.parent.name == "runs"
    assert data["results"][0]["passed"] is True


# --- runner + full corpus (§201: adversarial corpus runs every pass) --------


def test_runner_excludes_expected_yaml_and_respects_markers(tmp_path: Path) -> None:
    root = _write(tmp_path / "labs", {
        "d/s/expected.yaml": "expected_findings: []\nforbidden_findings: ['OAS*']",
        "d/s/openapi.yaml": "# just config\nhost: localhost\n",
    })
    (s,) = discover_scenarios(ProjectContext.from_root(root))
    from forge_doctor_api.lab.runner import run_scenario

    obs = run_scenario(ProjectContext.from_root(root), s)
    assert obs.findings == []


def test_full_corpus_is_green() -> None:
    """The repository labs/ tree: every runnable scenario passes.

    A scenario requiring an absent extra (e.g. graphql under a minimal
    install) is a recorded skip — not a failure and not a silent pass.
    Under a full install there are no skips at all.
    """
    from forge_doctor_api.lab.capabilities import extras_present

    report = run_labs(ProjectContext.from_root(REPO_LABS))
    failures = [
        f"{r.domain}/{r.name}"
        for r in report.results
        if not r.passed and not r.skipped
    ]
    assert failures == []
    assert len(report.results) >= 20
    assert all(r.skip_reason for r in report.results if r.skipped)
    if "graphql" in extras_present():
        assert report.skipped == 0
    else:
        assert report.skipped >= 1  # graphql scenarios must degrade


def test_corpus_covers_required_domains() -> None:
    domains = {
        s.domain for s in discover_scenarios(ProjectContext.from_root(REPO_LABS))
    }
    required = {
        "openapi", "rest", "graphql", "grpc", "asyncapi",
        "security", "reliability", "performance", "contracts",
        "adversarial", "golden",
    }
    assert required <= domains


def test_corpus_is_deterministic() -> None:
    a = _without_measurements(run_labs(ProjectContext.from_root(REPO_LABS)).to_dict())
    b = _without_measurements(run_labs(ProjectContext.from_root(REPO_LABS)).to_dict())
    assert a == b


def _without_measurements(data: dict) -> dict:
    """Timing/memory are harness measurements, not decision output —
    they vary legitimately across runs (spec 058)."""
    for key in ("results", "families", "domains"):
        for entry in data.get(key, []):
            entry["elapsed_ms"] = 0
            entry["peak_bytes"] = 0
    return data


def test_demo_scenarios_present() -> None:
    """§226-§229 demo targets exist and pass as lab scenarios."""
    names = {
        f"{s.domain}/{s.name}"
        for s in discover_scenarios(ProjectContext.from_root(REPO_LABS))
    }
    assert "contracts/breaking-change-client-impact" in names
    assert "performance/downstream-p95" in names
    assert "reliability/retry-amplification" in names
    assert "security/bola-candidate" in names


def test_negative_space_scenarios_exist() -> None:
    """Review note: scenarios where zero findings is the expected result."""
    scenarios = discover_scenarios(ProjectContext.from_root(REPO_LABS))
    negative = [s for s in scenarios if not s.expected.findings]
    assert len(negative) >= 5


# -- spec 058: real-world corpus + metrics -----------------------------------

def test_realworld_corpus_present_and_required() -> None:
    """spec 058: >=15 realworld cases covering the required matrix."""
    scenarios = discover_scenarios(ProjectContext.from_root(REPO_LABS))
    real = [s for s in scenarios if s.domain == "realworld"]
    assert len(real) >= 15
    assert all(s.provenance for s in real), (
        "every realworld scenario needs a provenance block")
    assert all(not s.problems for s in real), (
        [f"{s.name}: {s.problems}" for s in real])


def test_realworld_missing_provenance_fails() -> None:
    labs_root = Path(__file__).parent / ".pytest-tmp" / "rwtree"
    case = labs_root / "realworld" / "noprov"
    case.mkdir(parents=True, exist_ok=True)
    (case / "expected.yaml").write_text(
        "expected_findings: []\n", encoding="utf-8")
    ctx = ProjectContext.from_root(labs_root)
    scenarios = discover_scenarios(ctx)
    assert scenarios[0].problems
    obs = run_scenario(ctx, scenarios[0])
    result = compare(scenarios[0], obs)
    assert not result.passed
    assert result.problems


def test_family_score_metrics() -> None:
    score = FamilyScore(
        family="OAS", expected=4, hits=3, misses=1, false_positives=2,
        sample_size=10, unknowns=2, unsupported=1, parse_failures=0,
        elapsed_ms=50, peak_bytes=1024)
    assert score.tp == 3 and score.fp == 2 and score.fn == 1
    assert score.precision == 0.6
    assert score.recall == 0.75
    assert score.unknown_rate == 0.2
    assert score.unsupported_rate == 0.1
    assert score.coverage_confidence == "medium"
    d = score.to_dict()
    assert d["coverage_confidence"] == "medium"
    assert d["unknown_rate"] == 0.2


def test_run_records_metrics() -> None:
    report = run_labs(ProjectContext.from_root(REPO_LABS))
    assert any(r.sample_size > 0 for r in report.results)
    assert any(r.elapsed_ms >= 0 for r in report.results)
    assert any(f.coverage_confidence in ("low", "medium")
               for f in report.families)


# -- spec 071/073: capability matrix (minimal vs full install) --------------

def test_requires_extras_and_domains_parsed(tmp_path: Path) -> None:
    _write(tmp_path / "graphql" / "case", {
        "expected.yaml": (
            "run: [graphql]\n"
            "requires_extras: [graphql]\n"
            "requires_domains: [graphql]\n"
            "expected_findings: []\n"),
    })
    (scenario,) = discover_scenarios(ProjectContext.from_root(tmp_path))
    assert scenario.requires_extras == ("graphql",)
    assert scenario.requires_domains == ("graphql",)


def test_scenario_requirements_inferred(tmp_path: Path) -> None:
    """Domain and explicit `run:` imply the graphql extra; defaults don't."""
    from forge_doctor_api.lab import scenario_requirements

    _write(tmp_path / "graphql" / "by-domain", {
        "expected.yaml": "expected_findings: []\n"})
    _write(tmp_path / "golden" / "by-run", {
        "expected.yaml":
            "run: [graphql]\nexpected_findings: []\n"})
    _write(tmp_path / "golden" / "by-default", {
        "expected.yaml": "expected_findings: []\n"})
    scenarios = {
        f"{s.domain}/{s.name}": s
        for s in discover_scenarios(ProjectContext.from_root(tmp_path))
    }
    assert scenario_requirements(
        scenarios["graphql/by-domain"]) == ("graphql",)
    assert scenario_requirements(
        scenarios["golden/by-run"]) == ("graphql",)
    assert scenario_requirements(scenarios["golden/by-default"]) == ()


def test_missing_extra_skips_with_reason(
        tmp_path: Path, monkeypatch) -> None:
    """Absent extras produce a recorded skip — not a failure, not a pass."""
    from forge_doctor_api.lab import capabilities

    monkeypatch.setattr(capabilities, "_find_spec", lambda name: None)
    _write(tmp_path / "graphql" / "needs-gql", {
        "expected.yaml":
            "run: [graphql]\nrequires_extras: [graphql]\n"
            "expected_findings: [GQL007]\n"})
    _write(tmp_path / "openapi" / "plain", {
        "readme.md": "# no API markers here\n",
        "expected.yaml": "expected_findings: []\n"})
    report = run_labs(ProjectContext.from_root(tmp_path))
    skipped = {f"{r.domain}/{r.name}": r for r in report.results if r.skipped}
    assert set(skipped) == {"graphql/needs-gql"}
    assert "graphql" in skipped["graphql/needs-gql"].skip_reason
    assert report.skipped == 1
    assert report.failed == 0
    assert report.passed == 1  # the openapi scenario still ran
    # skipped scenarios contribute no family evidence either way
    assert all(f.expected == 0 for f in report.families
               if f.family == "GQL")


def test_run_record_records_install_profile(
        tmp_path: Path, monkeypatch) -> None:
    """Spec 073: run records persist which extras were present."""
    from forge_doctor_api.lab import capabilities

    monkeypatch.setattr(
        capabilities, "_find_spec",
        lambda name: object() if name == "mcp" else None)
    report = run_labs(ProjectContext.from_root(tmp_path))
    data = report.to_dict()
    assert data["extras_present"] == ["mcp"]
    assert data["extras_absent"] == ["graphql"]


def test_minimal_profile_still_counts_scenarios(
        tmp_path: Path, monkeypatch) -> None:
    """A minimal install reports full coverage intent: every scenario
    is accounted for as passed, failed, or skipped-with-reason."""
    from forge_doctor_api.lab import capabilities

    monkeypatch.setattr(capabilities, "_find_spec", lambda name: None)
    report = run_labs(ProjectContext.from_root(REPO_LABS))
    assert report.failed == 0
    assert report.skipped >= 1
    assert report.passed + report.failed + report.skipped == len(
        report.results)


def test_oss_scenarios_require_strong_provenance(tmp_path: Path) -> None:
    """Spec 077: `oss` scenarios must name source, pinned ref, license,
    and the vendored bytes' sha256 — weaker blocks are problems."""
    case = tmp_path / "oss" / "weak"
    case.mkdir(parents=True)
    (case / "readme.md").write_text("# no API markers\n")
    (case / "expected.yaml").write_text(
        "provenance: {source: somewhere, retrieved: today}\n"
        "expected_findings: []\n")
    report = run_labs(ProjectContext.from_root(tmp_path))
    result = next(r for r in report.results if r.domain == "oss")
    assert not result.passed
    assert any("provenance" in p for p in result.problems)


def test_oss_result_carries_corpus_origin_into_run_record() -> None:
    """Spec 077: the run record lists the corpus origin per scenario —
    provenance lands on every result, pass or fail."""
    report = run_labs(ProjectContext.from_root(REPO_LABS))
    oss = [r for r in report.results if r.domain == "oss"]
    assert oss, "labs/oss corpus missing"
    for r in oss:
        prov = dict(r.provenance)
        assert {"source", "upstream_ref", "license", "sha256"} <= set(prov)
    record = report.to_dict()
    origin = dict(record["results"][
        [r["name"] for r in record["results"]].index("oai-petstore")][
        "provenance"])
    assert origin["sha256"].startswith("cefa")


def test_per_domain_scores_reported() -> None:
    """Spec 085: the lab report aggregates precision/recall per domain
    alongside the existing per-family scores — JSON + model."""
    report = run_labs(ProjectContext.from_root(REPO_LABS))
    domains = {d.domain: d for d in report.domains}
    assert "workspace" in domains, "multi-repo workspace scenario missing"
    assert "openapi" in domains
    for d in report.domains:
        assert d.scenarios >= 1
        assert d.expected == d.hits + d.misses
    as_dict = report.to_dict()
    assert as_dict["domains"], "domains key missing from lab JSON"
    ws = domains["workspace"]
    assert ws.hits == 2 and ws.misses == 0


def test_workspace_scenario_proves_cross_tree_link() -> None:
    """Spec 085: service/client/gateway trees — client call sites are
    recorded and the unresolved template URL is an honest unknown."""
    report = run_labs(ProjectContext.from_root(REPO_LABS))
    ws = next(r for r in report.results if r.domain == "workspace")
    assert ws.passed
    assert ws.unknowns >= 1
