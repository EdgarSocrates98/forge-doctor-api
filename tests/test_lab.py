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
    """The repository labs/ tree: every scenario incl. adversarial passes."""
    report = run_labs(ProjectContext.from_root(REPO_LABS))
    failures = [f"{r.domain}/{r.name}" for r in report.results if not r.passed]
    assert failures == []
    assert len(report.results) >= 20


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
    for key in ("results", "families"):
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
