"""Spec 079 — security/reliability precision: auth chains, retry
topology, timeout budgets, idempotency, cache precision, gateway/mesh
declared-evidence joins.
"""

from __future__ import annotations

from pathlib import Path

from forge_doctor_api.analyzers.cache.graph import build_cache_graph
from forge_doctor_api.analyzers.cache.model import CacheLayer
from forge_doctor_api.analyzers.cache.scan import load_cache_model
from forge_doctor_api.analyzers.gateway import load_gateway_models
from forge_doctor_api.analyzers.openapi.parser import load_openapi_project
from forge_doctor_api.analyzers.routes import FastApiAdapter
from forge_doctor_api.checks.apisec import run_security_checks
from forge_doctor_api.checks.relapi import run_reliability_checks
from forge_doctor_api.checks.relapi.engine import run_depth_checks
from forge_doctor_api.core.context import ProjectContext
from forge_doctor_api.reliability import (
    IdempotencyVerdict,
    load_reliability_model,
)
from forge_doctor_api.reliability.config import gateway_edge_policies
from forge_doctor_api.reliability.model import (
    ApiReliabilityModel,
    TimeoutConfig,
)
from forge_doctor_api.security import load_security_model

HEADER = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\n"

SECURED_OAS = HEADER + (
    "paths:\n  /users/{user_id}:\n    get:\n"
    "      operationId: getUser\n"
    "      security:\n        - oauth: []\n"
    "      responses: {'200': {description: ok}}\n"
    "components:\n  securitySchemes:\n"
    "    oauth: {type: oauth2, flows: {}}\n"
)

ANON_OAS = HEADER + (
    "paths:\n  /users/{user_id}:\n    get:\n"
    "      operationId: getUser\n"
    "      security: []\n"
    "      responses: {'200': {description: ok}}\n"
)


def _ctx(tmp_path: Path, files: dict[str, str]) -> ProjectContext:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return ProjectContext.from_root(tmp_path)


def _fastapi(ctx: ProjectContext):
    return FastApiAdapter().scan(ctx, "svc")


def _ids(findings) -> list[str]:
    return [f.id for f in findings]


# ---------- auth chain (APISEC013) ----------


def test_auth_chain_break_declared_unenforced(tmp_path: Path) -> None:
    """Contract declares oauth; impl route has no Security() - break."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": SECURED_OAS,
        "app.py": (
            "from fastapi import FastAPI\napp = FastAPI()\n"
            "@app.get('/users/{user_id}')\n"
            "def getUser(user_id: int):\n    pass\n"),
    })
    routes = _fastapi(ctx)
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=routes)
    link = next(x for x in m.auth_chain if x.operation != "")
    assert link.scheme_declared == "oauth"
    assert link.enforcement_point == "contract-only"
    assert link.chain_complete is False
    assert link.evidence_refs
    f = next(f for f in run_security_checks(m, openapi=oas)
             if f.id == "APISEC013")
    assert "declared-but-unenforced" in f.description
    assert f.unknowns


def test_auth_chain_break_enforced_undeclared(tmp_path: Path) -> None:
    """Anonymous contract but impl route carries Security() - break."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": ANON_OAS,
        "app.py": (
            "from fastapi import FastAPI, Security\napp = FastAPI()\n"
            "@app.get('/users/{user_id}')\n"
            "def getUser(user_id: int, k=Security(chk)):\n    pass\n"),
    })
    routes = _fastapi(ctx)
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=routes)
    link = next((x for x in m.auth_chain if x.chain_complete is False),
                None)
    assert link is not None
    assert link.enforcement_point == "implementation"
    f = next(f for f in run_security_checks(m, openapi=oas)
             if f.id == "APISEC013")
    assert "enforced-but-undeclared" in f.description


def test_auth_chain_complete_no_findings(tmp_path: Path) -> None:
    """Declared oauth + Security() dep on the route - chain complete."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": SECURED_OAS,
        "app.py": (
            "from fastapi import FastAPI, Security\napp = FastAPI()\n"
            "@app.get('/users/{user_id}')\n"
            "def getUser(user_id: int, k=Security(chk)):\n    pass\n"),
    })
    routes = _fastapi(ctx)
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()),
                            openapi=oas, routes=routes)
    link = m.auth_chain[0]
    assert link.chain_complete is True
    assert link.enforcement_point == "implementation"
    assert "APISEC013" not in _ids(run_security_checks(m, openapi=oas))


def test_auth_chain_no_planes_no_records(tmp_path: Path) -> None:
    """No contract security, no routes, no gateway - no chain records."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /a:\n    get:\n      operationId: a\n"
            "      responses: {'200': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    m = load_security_model(ctx, list(ctx.iter_files()), openapi=oas)
    assert m.auth_chain == ()
    assert "APISEC013" not in _ids(run_security_checks(m, openapi=oas))


# ---------- idempotency (RELAPI008) ----------


def test_relapi008_mutation_without_evidence(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      responses: {'201': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    f = next(f for f in run_reliability_checks(
        rel, operations=oas.operations) if f.id == "RELAPI008")
    assert "createPet" in f.description or "POST /pets" in f.description
    assert "no declared idempotency" in f.description
    assert f.unknowns


def test_relapi008_silent_with_declared_key_header(tmp_path: Path) -> None:
    """Config idempotency bound via operationId -> capability evidence."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      responses: {'201': {description: ok}}\n"),
        "cfg.yaml": (
            "endpoints:\n  - name: createPet\n"
            "    idempotency:\n      key_header: Idempotency-Key\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    bound = next(i for i in rel.idempotency if i.subject == "createPet")
    assert bound.verdict is IdempotencyVerdict.IDEMPOTENT
    assert "RELAPI008" not in _ids(
        run_reliability_checks(rel, operations=oas.operations))


def test_relapi008_silent_with_x_idempotency_key(tmp_path: Path) -> None:
    """`x-idempotency-key` contract extension is capability evidence."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      x-idempotency-key: Idempotency-Key\n"
            "      responses: {'201': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    bound = next(i for i in rel.idempotency if i.subject == "createPet")
    assert bound.verdict is IdempotencyVerdict.IDEMPOTENT
    assert "RELAPI008" not in _ids(
        run_reliability_checks(rel, operations=oas.operations))


def test_relapi008_bound_non_idempotent(tmp_path: Path) -> None:
    """`x-idempotent: false` is asserted non-idempotent - finding names
    the bound subject, not just the gap."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      x-idempotent: false\n"
            "      responses: {'201': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    bound = next(i for i in rel.idempotency if i.subject == "createPet")
    assert bound.verdict is IdempotencyVerdict.NON_IDEMPOTENT
    f = next(f for f in run_reliability_checks(
        rel, operations=oas.operations) if f.id == "RELAPI008")
    assert "'createPet'" in f.description


def test_relapi008_no_verb_exemption(tmp_path: Path) -> None:
    """PUT/DELETE are RFC-idempotent but verbs alone never decide."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets/{id}:\n    put:\n      operationId: putPet\n"
            "      responses: {'200': {description: ok}}\n    delete:\n"
            "      operationId: delPet\n"
            "      responses: {'204': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    hits = [f for f in run_reliability_checks(rel, operations=oas.operations)
            if f.id == "RELAPI008"]
    assert len(hits) == 2


def test_relapi008_get_never_flags(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    get:\n      operationId: listPets\n"
            "      responses: {'200': {description: ok}}\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    assert "RELAPI008" not in _ids(
        run_reliability_checks(rel, operations=oas.operations))


# ---------- gateway/mesh declared-config vocab ----------


def test_kong_scalar_retries_and_timeouts(tmp_path: Path) -> None:
    """Kong `retries: N` scalar + *_timeout keys become policies."""
    ctx = _ctx(tmp_path, {
        "kong.yaml": (
            "_format_version: '3.0'\n"
            "services:\n  - name: payments-service\n"
            "    host: payments.internal\n"
            "    retries: 5\n"
            "    connect_timeout: 2000\n"
            "    routes:\n      - paths: [/pay]\n"),
    })
    rel = load_reliability_model(ctx, list(ctx.iter_files()))
    retries = {r.scope: r for r in rel.retry_policies}
    assert retries["payments-service"].max_attempts == 5
    timeouts = {t.scope: t for t in rel.timeouts}
    assert timeouts["payments-service"].timeout_ms == 2000


def test_istio_nested_retries_and_per_try_timeout(tmp_path: Path) -> None:
    """Istio `retries: {attempts, perTryTimeout}` joins the model."""
    ctx = _ctx(tmp_path, {
        "vs.yaml": (
            "apiVersion: networking.istio.io/v1beta1\n"
            "kind: VirtualService\n"
            "metadata: {name: reviews}\n"
            "spec:\n  hosts: [reviews]\n"
            "  http:\n  - name: reviews-route\n"
            "    retries: {attempts: 3, perTryTimeout: 2s}\n"),
    })
    rel = load_reliability_model(ctx, list(ctx.iter_files()))
    retries = {r.scope: r for r in rel.retry_policies}
    assert retries["reviews-route"].max_attempts == 3
    timeouts = {t.scope: t for t in rel.timeouts}
    assert timeouts["reviews-route"].timeout_ms == 2000


def test_gateway_edge_policies_scoped(tmp_path: Path) -> None:
    """Declared gateway retry/timeout entries become `dialect->subject`
    edge-scoped evidence for the depth checks."""
    ctx = _ctx(tmp_path, {
        "kong.yaml": (
            "_format_version: '3.0'\n"
            "services:\n  - name: payments-service\n"
            "    host: payments.internal\n"
            "    retries: 5\n"
            "    connect_timeout: 2000\n"
            "    routes:\n      - paths: [/pay]\n"),
    })
    gateways, meshes, _u = load_gateway_models(ctx, list(ctx.iter_files()))
    retries, timeouts = gateway_edge_policies(gateways, meshes)
    edge_r = next(r for r in retries
                  if r.scope == "kong->payments-service")
    assert edge_r.max_attempts == 5
    edge_t = next(t for t in timeouts
                  if t.scope == "kong->payments-service")
    assert edge_t.timeout_ms == 2000


def test_apirel002_edge_scoped_timeout_counts() -> None:
    """An edge-scoped caller budget (`a->b`) is evidence for that edge."""
    model = ApiReliabilityModel(
        timeouts=(
            TimeoutConfig(scope="edge->svc", timeout_ms=100),
            TimeoutConfig(scope="svc", timeout_ms=5000),
        ),
    )
    findings = run_depth_checks(model, (("edge", "svc"),))
    assert "APIREL002" in _ids(findings)


# ---------- cache precision ----------


def test_cache_header_only_records_unknown(tmp_path: Path) -> None:
    """Cache-Control header name alone -> policy + explicit unknown."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    get:\n      operationId: listPets\n"
            "      responses:\n        '200':\n          description: ok\n"
            "          headers:\n            Cache-Control:\n"
            "              schema: {type: string}\n"),
    })
    oas = load_openapi_project(ctx)
    cache = load_cache_model(ctx, list(ctx.iter_files()), openapi=oas)
    pol = next(p for p in cache.policies if p.subject != "")
    assert pol.layer is CacheLayer.CLIENT
    assert pol.ttl is None and pol.key is None
    u = next(u for u in cache.unknowns if u.subject == pol.subject)
    assert "ttl" in u.missing and "stale_policy" in u.missing


def test_apicache003_shared_key_writer_reader(tmp_path: Path) -> None:
    """Shared declared `key` spanning a writer + reader subject."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n"
            "    get:\n      operationId: listPets\n"
            "      responses: {'200': {description: ok}}\n"
            "    post:\n      operationId: createPet\n"
            "      responses: {'201': {description: ok}}\n"),
        "cfg.yaml": (
            "cache:\n  listPets: {key: pets-key, ttl: 60}\n"
            "  createPet: {key: pets-key, ttl: 0}\n"),
    })
    oas = load_openapi_project(ctx)
    cache = load_cache_model(ctx, list(ctx.iter_files()), openapi=oas)
    _graph, findings = build_cache_graph(cache, oas)
    f = next(f for f in findings if f.id == "APICACHE003")
    assert "pets-key" in f.description
    assert "listPets" in f.description and "createPet" in f.description


def test_apicache003_silent_distinct_keys(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n"
            "    get:\n      operationId: listPets\n"
            "      responses: {'200': {description: ok}}\n"
            "    post:\n      operationId: createPet\n"
            "      responses: {'201': {description: ok}}\n"),
        "cfg.yaml": (
            "cache:\n  listPets: {key: pets-r}\n"
            "  createPet: {key: pets-w}\n"),
    })
    oas = load_openapi_project(ctx)
    cache = load_cache_model(ctx, list(ctx.iter_files()), openapi=oas)
    _graph, findings = build_cache_graph(cache, oas)
    assert "APICACHE003" not in _ids(findings)


# ---------- model-level invariants ----------


def test_relapi008_no_name_similarity_join(tmp_path: Path) -> None:
    """An idempotency subject that merely *resembles* the op does not
    bind - only declared identifiers join."""
    ctx = _ctx(tmp_path, {
        "openapi.yaml": HEADER + (
            "paths:\n  /pets:\n    post:\n      operationId: createPet\n"
            "      responses: {'201': {description: ok}}\n"),
        "cfg.yaml": (
            "endpoints:\n  - name: createAPet\n"
            "    idempotency:\n      key_header: Idempotency-Key\n"),
    })
    oas = load_openapi_project(ctx)
    rel = load_reliability_model(ctx, list(ctx.iter_files()), openapi=oas)
    assert "RELAPI008" in _ids(
        run_reliability_checks(rel, operations=oas.operations))


def test_gateway_edge_retry_join_depth(tmp_path: Path) -> None:
    """kong->svc edge retry + svc retry -> APIREL001 amplification."""
    ctx = _ctx(tmp_path, {
        "kong.yaml": (
            "_format_version: '3.0'\n"
            "services:\n  - name: payments-service\n"
            "    host: payments.internal\n"
            "    retries: 3\n"
            "    routes:\n      - paths: [/pay]\n"),
        "app.yaml": (
            "service:\n  name: payments-service\n"
            "  retry_policy: {max_attempts: 3}\n"),
    })
    gateways, meshes, _u = load_gateway_models(ctx, list(ctx.iter_files()))
    rel = load_reliability_model(ctx, list(ctx.iter_files()))
    er, et = gateway_edge_policies(gateways, meshes)
    from dataclasses import replace
    rel = replace(
        rel,
        retry_policies=tuple(sorted(
            (*rel.retry_policies, *er), key=lambda r: r.scope)),
        timeouts=tuple(sorted(
            (*rel.timeouts, *et), key=lambda t: t.scope)))
    edges = tuple(
        (gw.dialect.value, rt.service)
        for gw in gateways for rt in gw.routes if rt.service)
    findings = run_depth_checks(rel, edges)
    amp = next((f for f in findings if f.id == "APIREL001"), None)
    assert amp is not None
    assert "9" in amp.description  # 3 x 3 actual multiplication
