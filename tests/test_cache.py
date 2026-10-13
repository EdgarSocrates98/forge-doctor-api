"""Spec 034 — declared cache model (§151-153)."""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.cache import (
    CacheLayer,
    load_cache_model,
)
from forge_doctor_api.analyzers.openapi.model import (
    OpenApiOperation,
    OpenApiProjectModel,
    OpenApiResponse,
    OperationSource,
)
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.core.models import Confidence, SourceLocation

_LOC = SourceLocation(path="api.yaml", line=1)

_CONFIG = """\
cache:
  /pay:
    ttl: 60
    key: account_id
    invalidation: on-write
cdn:
  /static:
    ttl: 300
"""


def _ctx(root: Path, files: dict[str, str]) -> ProjectContext:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return ProjectContext(root=root)


def _openapi(*, cached_op: bool, writer: bool) -> OpenApiProjectModel:
    ops = [OpenApiOperation(
        location=_LOC, pointer="#/paths/~1pay/get", source=OperationSource.PATH,
        method="GET", path="/pay", identity="GET /pay",
        response_pointers=("#/paths/~1pay/get/responses/200",))]
    if writer:
        ops.append(OpenApiOperation(
            location=_LOC, pointer="#/paths/~1pay/post",
            source=OperationSource.PATH, method="POST", path="/pay",
            identity="POST /pay"))
    resp = OpenApiResponse(
        location=_LOC, pointer="#/paths/~1pay/get/responses/200",
        status="200",
        header_names=("Cache-Control",) if cached_op else ())
    return OpenApiProjectModel(
        schema_version="3.0", operations=tuple(ops), responses=(resp,))


class TestDeclaredPolicies:
    def test_config_policies_by_layer(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"cache.yaml": _CONFIG})
        model = load_cache_model(ctx, sorted(ctx.iter_files()))
        by_subject = {p.subject: p for p in model.policies}
        pay = by_subject["/pay"]
        assert pay.layer is CacheLayer.SERVICE
        assert pay.ttl == "60" and pay.key == "account_id"
        assert pay.invalidation == "on-write"
        assert by_subject["/static"].layer is CacheLayer.CDN

    def test_cache_control_header_declares_client_policy(self) -> None:
        ctx = ProjectContext(root=Path.cwd())
        model = load_cache_model(
            ctx, [], openapi=_openapi(cached_op=True, writer=False))
        assert model.policies[0].layer is CacheLayer.CLIENT
        assert model.policies[0].subject == "GET /pay"
        # header value is not retained → ttl stays unknown, not guessed
        assert model.policies[0].ttl is None

    def test_no_cache_evidence_empty_model(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"plain.yaml": "foo: bar\n"})
        model = load_cache_model(
            ctx, sorted(ctx.iter_files()),
            openapi=_openapi(cached_op=False, writer=False))
        assert model.policies == () and model.risks == ()

    def test_malformed_cache_marked_unknown(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"cache.yaml": "cache: [unclosed\n"})
        model = load_cache_model(ctx, sorted(ctx.iter_files()))
        assert model.policies == ()
        assert model.unknowns[0].subject == "cache.yaml"

    def test_gateway_layer_declared(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"gw.yaml":
                              "cache:\n  /x:\n    layer: gateway\n"
                              "    ttl: 5\n"})
        model = load_cache_model(ctx, sorted(ctx.iter_files()))
        assert model.policies[0].layer is CacheLayer.GATEWAY


class TestInvalidationRisk:
    def test_cached_path_with_writer_is_candidate(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"cache.yaml": _CONFIG})
        model = load_cache_model(
            ctx, sorted(ctx.iter_files()),
            openapi=_openapi(cached_op=False, writer=True))
        assert len(model.risks) == 1
        risk = model.risks[0]
        assert risk.subject == "/pay"
        assert risk.confidence is Confidence.LOW
        assert risk.evidence

    def test_readonly_path_no_risk(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"cache.yaml": _CONFIG})
        model = load_cache_model(
            ctx, sorted(ctx.iter_files()),
            openapi=_openapi(cached_op=False, writer=False))
        assert model.risks == ()

    def test_deterministic(self, tmp_path) -> None:
        ctx = _ctx(tmp_path, {"cache.yaml": _CONFIG})
        files = sorted(ctx.iter_files())
        a = load_cache_model(ctx, files, openapi=_openapi(cached_op=True,
                                                          writer=True))
        b = load_cache_model(ctx, files, openapi=_openapi(cached_op=True,
                                                          writer=True))
        assert a == b
