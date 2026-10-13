"""Spec 065 — incremental engine: AnalysisCache + scan integration.

The cache is opt-in (``incremental=True`` / ``--incremental``), stores
analyzer-level model dicts keyed by artifact sha256 + analyzer +
tool version + config digest, and never stores findings or unknowns.
Cold vs warm reports must be byte-identical; touching one artifact
invalidates only the keys of analyzers that consumed it.
"""

from __future__ import annotations

import json
from pathlib import Path

from forge_doctor_api.core.cache import AnalysisCache
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.scan import scan_project

OPENAPI = """\
openapi: 3.0.3
info: {title: T, version: "1.0"}
paths:
  /pets:
    get:
      operationId: listPets
      responses: {"200": {description: ok}}
"""

OTLP = (
    '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name",'
    '"value":{"stringValue":"svc"}}]},"scopeSpans":[{"scope":{},"spans":['
    '{"traceId":"t00000001","spanId":"s00000001-0000","name":"GET /x",'
    '"kind":2,"startTimeUnixNano":"0","endTimeUnixNano":"100",'
    '"status":{"code":1}}]}]}]}'
)

TF = 'resource "aws_s3_bucket" "b" { bucket = "x" }\n'


def _project(tmp_path: Path) -> Path:
    (tmp_path / "api.yaml").write_text(OPENAPI, encoding="utf-8")
    (tmp_path / "traces.json").write_text(OTLP, encoding="utf-8")
    (tmp_path / "main.tf").write_text(TF, encoding="utf-8")
    return tmp_path


def test_default_creates_no_cache(tmp_path: Path) -> None:
    root = _project(tmp_path)
    scan_project(ProjectContext.from_root(root))
    assert not (root / ".forge-doctor").exists()


def test_cold_warm_equivalence(tmp_path: Path) -> None:
    root = _project(tmp_path)
    cold = scan_project(ProjectContext.from_root(root))
    scan_project(ProjectContext.from_root(root), incremental=True)
    warm = scan_project(ProjectContext.from_root(root), incremental=True)
    assert cold.to_json() == warm.to_json()


def test_cache_dir_only_with_flag(tmp_path: Path) -> None:
    root = _project(tmp_path)
    scan_project(ProjectContext.from_root(root), incremental=True)
    cache_dir = root / ".forge-doctor" / "cache"
    assert cache_dir.is_dir()
    entries = list(cache_dir.glob("*.json"))
    assert entries, "warm run must persist analyzer models"
    analyzers = set()
    for entry in entries:
        payload = json.loads(entry.read_text(encoding="utf-8"))
        assert set(payload) >= {"key", "analyzer", "tool_version", "model"}
        assert isinstance(payload["model"], dict)
        # envelope carries no check findings or report unknowns —
        # only the analyzer-level compact model
        assert "findings" not in payload
        assert "unknowns" not in payload
        assert "findings" not in payload["model"]
        analyzers.add(payload["analyzer"])
    assert {"openapi", "runtime", "iac"} <= analyzers


def test_touching_one_artifact_invalidates_only_its_keys(
        tmp_path: Path) -> None:
    root = _project(tmp_path)
    cache = AnalysisCache(root, tool_version="t")
    assert cache.get("openapi", ["sha-a"], "") is None
    cache.put("openapi", ["sha-a"], "", {"x": 1})
    cache.put("runtime", ["sha-b"], "", {"y": 2})
    assert cache.get("openapi", ["sha-a"], "") == {"x": 1}
    # api.yaml changes → only openapi's key changes
    assert cache.get("openapi", ["sha-a2"], "") is None
    assert cache.get("runtime", ["sha-b"], "") == {"y": 2}
    assert cache.hits == 2
    assert cache.misses == 2


def test_corrupt_entry_falls_back(tmp_path: Path) -> None:
    root = _project(tmp_path)
    cache = AnalysisCache(root, tool_version="t")
    key = cache.key("openapi", ["sha-a"], "")
    cache_dir = root / ".forge-doctor" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{key}.json").write_text("{not json", encoding="utf-8")
    assert cache.get("openapi", ["sha-a"], "") is None
    # wrong tool version → miss
    cache.put("openapi", ["sha-a"], "", {"x": 1})
    stale = AnalysisCache(root, tool_version="other")
    assert stale.get("openapi", ["sha-a"], "") is None
    # malformed model payload → scan falls back cleanly
    key2 = cache.key("iac", ["sha-c"], "")
    (cache_dir / f"{key2}.json").write_text(
        json.dumps({"key": key2, "analyzer": "iac",
                    "tool_version": "t",
                    "model": {"bogus_field": 1}}),
        encoding="utf-8")
    ctx = ProjectContext.from_root(root)
    report = scan_project(ctx, incremental=True)
    assert report.findings is not None  # full analysis still works


def test_incremental_flag_warm_scan(tmp_path: Path) -> None:
    root = _project(tmp_path)
    r1 = scan_project(ProjectContext.from_root(root),
                      incremental=True)
    r2 = scan_project(ProjectContext.from_root(root),
                      incremental=True)
    assert r1.to_json() == r2.to_json()
    # findings recompute identically — never replayed from cache
    assert [f.id for f in r1.findings] == [f.id for f in r2.findings]
