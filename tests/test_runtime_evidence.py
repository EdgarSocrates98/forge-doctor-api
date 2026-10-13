"""Runtime artifact ingestion + OBSAPI### tests (spec 014, §30-32, §84-86)."""

from __future__ import annotations

import json
from pathlib import Path

from forge_doctor_api.analyzers.runtime import load_runtime_project
from forge_doctor_api.checks.observability import run_observability_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Confidence


def _span(
    sid: str,
    tid: str,
    name: str,
    parent: str | None = None,
    dur: float = 100,
    kind: int = 2,
    code: int = 1,
    attrs: dict[str, str] | None = None,
) -> dict:
    return {
        "traceId": tid,
        "spanId": sid,
        "name": name,
        "parentSpanId": parent or "",
        "kind": kind,
        "startTimeUnixNano": "0",
        "endTimeUnixNano": str(int(dur * 1e6)),
        "attributes": [
            {"key": k, "value": {"stringValue": v}} for k, v in (attrs or {}).items()
        ],
        "status": {"code": code},
    }


def _otlp(spans: list[dict], service: str = "api") -> str:
    return json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": service},
                            }
                        ]
                    },
                    "scopeSpans": [{"scope": {}, "spans": spans}],
                }
            ]
        }
    )


NGINX = (
    '127.0.0.1 - - [10/Oct/2025:13:55:36 +0000] "GET /users HTTP/1.1" 200 1234'
    ' "-" "agent" x-request-id: abc-123\n'
    '127.0.0.1 - - [10/Oct/2025:13:55:37 +0000] "POST /users HTTP/1.1" 201 10 "-" "a"\n'
)


def _load(root: Path, files: dict[str, str], keep_spans: bool = True):
    for name, text in files.items():
        t = root / name
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
    rt = load_runtime_project(
        ProjectContext.from_root(root), list(files), keep_spans=keep_spans
    )
    return rt.traces, rt.observability, rt.unknowns


def _ids(findings) -> list[str]:
    return [f.id for f in findings]


# -- ingestion -------------------------------------------------------------


def test_otlp_spans_streamed(tmp_path: Path) -> None:
    spans = [
        _span("r", "t1", "GET /users", dur=200, attrs={"http.route": "/users"}),
        _span("c", "t1", "db_query", parent="r", dur=150, kind=3),
    ]
    traces, _, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    assert len(traces) == 1
    t = traces[0]
    assert t.trace_id == "t1" and t.span_count == 2
    assert t.root_service == "api"
    assert t.critical_path == ("/users", "db_query")
    assert not t.incomplete


def test_incomplete_trace_honest_critical_path(tmp_path: Path) -> None:
    spans = [_span("o", "t1", "orphan", parent="missing")]
    traces, _, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    assert traces[0].incomplete
    assert traces[0].critical_path == ()
    assert traces[0].unknowns


def test_summary_only_retention(tmp_path: Path) -> None:
    spans = [_span("r", "t1", "op", dur=10)]
    traces, _, _ = _load(tmp_path, {"t.json": _otlp(spans)}, keep_spans=False)
    assert traces[0].spans == () and traces[0].span_count == 1


def test_non_otlp_json_rejected(tmp_path: Path) -> None:
    """OTLP-looking-but-invalid JSON must not attribute (§101 analog)."""
    traces, obs, _ = _load(tmp_path, {"data.json": '{"spans": "nope"}'})
    assert traces == () and obs.span_count == 0


def test_access_log_summaries(tmp_path: Path) -> None:
    _, obs, _ = _load(tmp_path, {"access.log": NGINX})
    assert obs.request_count == 2
    assert obs.signals.get("request_ids") == 1
    assert obs.signals.get("structured_logs") == 2


def test_streaming_10k_spans(tmp_path: Path) -> None:
    """§170-scale smoke: 10k spans stream without full retention."""
    spans = [_span(f"s{i}", f"t{i % 100}", f"op{i}", dur=1) for i in range(10_000)]
    traces, obs, _ = _load(tmp_path, {"big.json": _otlp(spans)}, keep_spans=False)
    assert obs.span_count == 10_000
    assert len(traces) == 100
    assert all(t.spans == () for t in traces)


# -- OBSAPI checks -----------------------------------------------------------


def test_obsapi001_no_correlation(tmp_path: Path) -> None:
    spans = [_span("r", "t1", "op", dur=10)]
    _, obs, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    assert "OBSAPI001" in _ids(run_observability_checks(obs))


def test_obsapi001_clean_with_correlation(tmp_path: Path) -> None:
    spans = [_span("r", "t1", "op", dur=10, attrs={"x-request-id": "a1"})]
    _, obs, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    assert "OBSAPI001" not in _ids(run_observability_checks(obs))


def test_obsapi002_orphan_gap(tmp_path: Path) -> None:
    spans = [_span("o", "t1", "op", parent="gone", dur=10)]
    _, obs, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    f = next(
        f for f in run_observability_checks(obs) if f.id == "OBSAPI002"
    )
    assert "parents absent" in f.description


def test_obsapi003_mixed_naming(tmp_path: Path) -> None:
    spans = [
        _span("a", "t1", "getUser", dur=1),
        _span("b", "t1", "list_items", dur=1),
        _span("c", "t1", "fetch-thing", dur=1),
    ]
    _, obs, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    assert "OBSAPI003" in _ids(run_observability_checks(obs))


def test_obsapi004_error_without_context(tmp_path: Path) -> None:
    spans = [_span("e", "t1", "op", code=2)]
    _, obs, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    f = next(f for f in run_observability_checks(obs) if f.id == "OBSAPI004")
    assert f.confidence is Confidence.LOW and f.unknowns


def test_obsapi004_clean_with_error_attrs(tmp_path: Path) -> None:
    spans = [_span("e", "t1", "op", code=2, attrs={"error.type": "Timeout"})]
    _, obs, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    assert "OBSAPI004" not in _ids(run_observability_checks(obs))


def test_obsapi005_missing_duration(tmp_path: Path) -> None:
    span_no_dur = {
        "traceId": "t1",
        "spanId": "x",
        "name": "op",
        "status": {"code": 1},
    }
    _, obs, _ = _load(tmp_path, {"t.json": _otlp([span_no_dur])})
    assert "OBSAPI005" in _ids(run_observability_checks(obs))


def test_rpc_semconv_operation_and_offset(tmp_path: Path) -> None:
    """§86: rpc.service + rpc.method map into operation; evidence carries offset."""
    spans = [
        _span(
            "r",
            "t1",
            "call",
            dur=10,
            attrs={"rpc.service": "UserSvc", "rpc.method": "Get"},
        )
    ]
    traces, _, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    span = traces[0].spans[0]
    assert span.operation == "UserSvc/Get"
    assert span.evidence[0].offset is not None
    text = (tmp_path / "t.json").read_text()
    assert text[span.evidence[0].offset] == "{"


def test_secret_attribute_redacted(tmp_path: Path) -> None:
    spans = [_span("r", "t1", "op", dur=1, attrs={"api_key": "supersecretvalue"})]
    traces, obs, _ = _load(tmp_path, {"t.json": _otlp(spans)})
    assert "supersecretvalue" not in traces[0].to_json()
    assert "supersecretvalue" not in obs.to_json()


def test_determinism(tmp_path: Path) -> None:
    files = {"t.json": _otlp([_span("a", "t1", "op")]), "a.log": NGINX}
    a = _load(tmp_path / "x", files)
    b = _load(tmp_path / "y", files)
    assert [t.to_dict() for t in a[0]] == [t.to_dict() for t in b[0]]
    assert a[1].to_dict() == b[1].to_dict()
